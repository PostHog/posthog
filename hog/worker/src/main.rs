// hog-worker does the file work of `hog error-tracking` with the Rust code posthog-cli runs, so
// both write the same bytes. hog starts one worker per command and talks to it in JSON lines over
// stdin and stdout. The worker sends {"type":"hello","protocol":1,"version":"0.1.0"}, then answers
// each request in order with {"ok":true,"result":R} or {"ok":false,"error":{"code","message"}},
// and keeps running after a failure. R for each `op`:
//   detect             {"sourcemap":[index],"composed":[],"mapping":[],"elf":[],"macho":[]}
//   read_pairs         {"pairs":[{"id":0,"sourcePath":"...",...} | {"skipped":"reason"} | null]}
//   inject             {"outcomes":[{"action","chunkId","warnings","pair"}]}
//   drop, save         {}
//   fingerprint        {"targets":[id]}, which record what each pair's files hold for `clean_up`
//   set_release        {}, for the `pairs` and `maps` it names
//   prepare            {"skipped":[{"id","reason"}],"prepared":[{"id","chunkId","contentHash",...}],
//                      "duplicates":["chunk id"]}, uploads in order and the first pair per chunk id
//   css_candidates     {"candidates":[{"id":0,"mapRealPath":"..."} | null]}
//   clean_up           {"deletedMaps":["..."],"warnings":["..."]}
//   proguard           {"contentHash":"...","size":640,"path":"..."} | {"invalid":"reason"}
//   load_maps          {"maps":[{"id":0,"chunkId","releaseId"} | {"unreadable"}]}
//   clone_metadata     {"map":{"id":1,...}}, the `to` map with the chunk id and release of `from`
//   write_maps         {}, every map or none
//   prepare_maps       the answer of `prepare`, with no duplicates
//   native_candidates  {"files":[{"candidates":[{"id",...} | {"problem"}]} | {"unparseable"}]}
//   dsym_slices        {"members":[{"slices":[{"id","uuid"}]} | {"unreadable"}]}
//   source_paths       {"sources":[{"paths":["..."]} | {"failed"}]}
//   pack_native        {"unreadable":[[{"path","message"}]],"containers":[{"contentHash",...} | {"failed"}
//                      | null]}, failed for every slice of a dSYM bundle that failed, and null for a
//                      native file that a dSYM which fits replaces
// Each architecture of a fat Mach-O is a binary with an id of its own. `pack_native` reads each
// list in `sources` when it packs the binaries that use it, keeps it only until they are packed,
// and answers one `unreadable` list for it, and one container per item.
// `prepare`, `prepare_maps` and `pack_native` write symbol sets to files for hog to send and let
// their pairs, maps and binaries go. The others stay in memory until hog closes stdin, which ends
// the worker. PROTOCOL changes whenever a request or an answer does, because hog and the worker
// ship as two files.

mod cleanup;
mod constant;
mod dsym;
mod guard;
mod hermes;
mod memory;
mod native;
mod node;
mod pair;
#[cfg(test)]
mod parity;
mod proguard;
mod sources;
mod store;
mod trace;
mod upload;
mod write;

use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    io::{self, BufRead, Write},
    path::{Path, PathBuf},
};

use pair::{Action, SourcePair, Unreadable};
use store::Store;
use trace::Trace;

const PROTOCOL: u32 = 1;

const MILLIS_PER_SECOND: u64 = 1000;
const NANOS_PER_MILLI: u32 = 1_000_000;

const BAD_REQUEST: &str = "bad_request";
const FAILED: &str = "failed";

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum Request {
    #[serde(rename_all = "camelCase")]
    Detect {
        files: Vec<Candidate>,
        public_path_prefix: Option<String>,
    },
    #[serde(rename_all = "camelCase")]
    ReadPairs {
        paths: Vec<String>,
        public_path_prefix: Option<String>,
    },
    Drop {
        ids: Vec<usize>,
    },
    #[serde(rename_all = "camelCase")]
    Inject {
        ids: Vec<usize>,
        mode: ReleaseMode,
        release_id: Option<String>,
        // hog's clock, in milliseconds, so its tests decide the timestamps in minted chunk ids.
        now: u64,
    },
    Save {
        ids: Vec<usize>,
    },
    Fingerprint {
        ids: Vec<usize>,
    },
    #[serde(rename_all = "camelCase")]
    SetRelease {
        #[serde(default)]
        pairs: Vec<usize>,
        #[serde(default)]
        maps: Vec<usize>,
        release_id: Option<String>,
    },
    Prepare {
        ids: Vec<usize>,
        mode: ReleaseMode,
        folder: Option<String>,
    },
    #[serde(rename_all = "camelCase")]
    CssCandidates {
        files: Vec<String>,
        public_path_prefix: Option<String>,
    },
    CleanUp {
        targets: Vec<usize>,
        css: Vec<usize>,
        roots: Vec<String>,
    },
    Proguard {
        path: String,
        folder: Option<String>,
    },
    LoadMaps {
        paths: Vec<String>,
    },
    CloneMetadata {
        from: usize,
        to: usize,
    },
    WriteMaps {
        ids: Vec<usize>,
    },
    PrepareMaps {
        ids: Vec<usize>,
        folder: Option<String>,
    },
    NativeCandidates {
        paths: Vec<String>,
    },
    DsymSlices {
        paths: Vec<String>,
    },
    SourcePaths {
        ids: Vec<usize>,
    },
    #[serde(rename_all = "camelCase")]
    PackNative {
        sources: Vec<Vec<String>>,
        items: Vec<PackItem>,
        folder: Option<String>,
        max_size: usize,
    },
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct PackItem {
    id: usize,
    // A place in the request's `sources`. Null packs the binary alone.
    sources: Option<usize>,
    chunk_id: String,
    // The dSYM bundle a slice comes from, a place hog numbers. Null for a native file.
    bundle: Option<usize>,
}

#[derive(Serialize)]
#[serde(untagged)]
enum Packed {
    Container(upload::Container),
    Failed { failed: String },
}

#[derive(Deserialize)]
struct Candidate {
    path: String,
    bundle: bool,
    map: bool,
    mapping: bool,
    // A native binary has any name, so discovery asks for the format its first bytes give.
    native: bool,
}

struct Detected {
    sourcemap: bool,
    composed: bool,
    mapping: bool,
    native: Option<native::Format>,
}

#[derive(Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum ReleaseMode {
    Event,
    SymbolSet,
}

#[derive(Serialize)]
#[serde(untagged)]
enum Answer {
    // Indices into the request's `files`.
    Detected {
        sourcemap: Vec<usize>,
        composed: Vec<usize>,
        mapping: Vec<usize>,
        elf: Vec<usize>,
        macho: Vec<usize>,
    },
    Pairs {
        pairs: Vec<PairAnswer>,
    },
    Outcomes {
        outcomes: Vec<Outcome>,
    },
    Targets {
        targets: Vec<usize>,
    },
    Prepared {
        skipped: Vec<upload::Skipped>,
        prepared: Vec<upload::Prepared>,
        duplicates: Vec<String>,
    },
    CssCandidates {
        candidates: Vec<Option<CssCandidateAnswer>>,
    },
    #[serde(rename_all = "camelCase")]
    Cleaned {
        deleted_maps: Vec<String>,
        warnings: Vec<String>,
    },
    Proguard(proguard::Built),
    Maps {
        maps: Vec<MapAnswer>,
    },
    Map {
        map: MapState,
    },
    NativeFiles {
        files: Vec<NativeFileAnswer>,
    },
    DsymMembers {
        members: Vec<DsymMemberAnswer>,
    },
    SourcePaths {
        sources: Vec<SourcePathsAnswer>,
    },
    Packed {
        unreadable: Vec<Vec<sources::Unreadable>>,
        containers: Vec<Option<Packed>>,
    },
    Done {},
}

#[derive(Serialize)]
#[serde(untagged)]
enum NativeFileAnswer {
    Parsed { candidates: Vec<CandidateAnswer> },
    Unparseable { unparseable: String },
}

#[derive(Serialize)]
#[serde(untagged)]
enum CandidateAnswer {
    Problem {
        problem: native::Problem,
    },
    #[serde(rename_all = "camelCase")]
    Valid {
        id: usize,
        debug_id: String,
        format: native::Format,
        // hog keeps the larger of two files with one debug id.
        size: usize,
    },
}

#[derive(Serialize)]
#[serde(untagged)]
enum DsymMemberAnswer {
    Read { slices: Vec<SliceAnswer> },
    Unreadable { unreadable: String },
}

#[derive(Serialize)]
struct SliceAnswer {
    id: usize,
    uuid: String,
}

#[derive(Serialize)]
#[serde(untagged)]
enum SourcePathsAnswer {
    Found { paths: Vec<String> },
    Failed { failed: String },
}

#[derive(Serialize)]
#[serde(untagged)]
enum MapAnswer {
    Loaded(MapState),
    Unreadable { unreadable: String },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MapState {
    id: usize,
    chunk_id: Option<String>,
    release_id: Option<String>,
}

fn map_state(id: usize, map: &hermes::MapFile) -> MapState {
    MapState {
        id,
        chunk_id: map.content.chunk_id.clone(),
        release_id: map.content.release_id.clone(),
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CssCandidateAnswer {
    id: usize,
    map_real_path: Option<String>,
}

#[derive(Serialize)]
#[serde(untagged)]
enum PairAnswer {
    Read(PairState),
    Skipped { skipped: String },
    Missing(()),
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PairState {
    id: usize,
    source_path: String,
    map_path: String,
    // hog matches ignore patterns against the map's canonical path.
    map_real_path: String,
    chunk_id: Option<String>,
    source_debug_id: Option<String>,
    map_chunk_id: Option<String>,
    map_release_id: Option<String>,
    map_debug_id: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Outcome {
    action: Action,
    chunk_id: String,
    warnings: Vec<String>,
    pair: PairState,
}

#[derive(Serialize)]
struct Hello<'a> {
    r#type: &'a str,
    protocol: u32,
    version: &'a str,
}

#[derive(Serialize)]
#[serde(untagged)]
enum Response {
    Ok { ok: bool, result: Answer },
    Failed { ok: bool, error: Failure },
}

#[derive(Serialize)]
struct Failure {
    code: &'static str,
    message: String,
}

impl Failure {
    fn bad_request(message: impl ToString) -> Self {
        Failure {
            code: BAD_REQUEST,
            message: message.to_string(),
        }
    }

    fn failed(message: impl ToString) -> Self {
        Failure {
            code: FAILED,
            message: message.to_string(),
        }
    }
}

fn display(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

fn state(id: usize, pair: &SourcePair) -> PairState {
    let map_real_path =
        dunce::canonicalize(&pair.map_path).unwrap_or_else(|_| pair.map_path.clone());

    PairState {
        id,
        source_path: display(&pair.source_path),
        map_path: display(&pair.map_path),
        map_real_path: display(&map_real_path),
        chunk_id: pair.chunk_id(),
        source_debug_id: pair.source_debug_id(),
        map_chunk_id: pair.map.chunk_id.clone(),
        map_release_id: pair.map.release_id.clone(),
        map_debug_id: pair.map.debug_id.clone(),
    }
}

struct Worker {
    pairs: Store<SourcePair>,
    maps: Store<hermes::MapFile>,
    binaries: Store<native::Binary>,
    targets: Store<cleanup::Target>,
    stylesheets: Store<cleanup::CssCandidate>,
    trace: Trace,
}

impl Worker {
    fn handle(&mut self, request: Request) -> Result<Answer, Failure> {
        match request {
            Request::Detect {
                files,
                public_path_prefix,
            } => self.detect(&files, public_path_prefix.as_deref()),
            Request::ReadPairs {
                paths,
                public_path_prefix,
            } => Ok(self.read_pairs(&paths, public_path_prefix.as_deref())),
            Request::Drop { ids } => {
                self.pairs.take_all(&ids)?;
                Ok(Answer::Done {})
            }
            Request::Inject {
                ids,
                mode,
                release_id,
                now,
            } => self.inject(&ids, mode, release_id.as_deref(), now),
            Request::Save { ids } => self.save(&ids),
            Request::Fingerprint { ids } => self.fingerprint(&ids),
            Request::SetRelease {
                pairs,
                maps,
                release_id,
            } => self.set_release(&pairs, &maps, release_id),
            Request::Prepare { ids, mode, folder } => self.prepare(&ids, mode, folder.as_deref()),
            Request::CssCandidates {
                files,
                public_path_prefix,
            } => Ok(self.css_candidates(&files, public_path_prefix.as_deref())),
            Request::CleanUp {
                targets,
                css,
                roots,
            } => self.clean_up(&targets, &css, &roots),
            Request::Proguard { path, folder } => {
                proguard::build(Path::new(&path), folder.as_deref().map(Path::new))
                    .map(Answer::Proguard)
                    .map_err(Failure::failed)
            }
            Request::LoadMaps { paths } => Ok(self.load_maps(&paths)),
            Request::CloneMetadata { from, to } => self.clone_metadata(from, to),
            Request::WriteMaps { ids } => self.write_maps(&ids),
            Request::PrepareMaps { ids, folder } => self.prepare_maps(&ids, folder.as_deref()),
            Request::NativeCandidates { paths } => Ok(self.native_candidates(&paths)),
            Request::DsymSlices { paths } => Ok(self.dsym_slices(&paths)),
            Request::SourcePaths { ids } => self.source_paths(&ids),
            Request::PackNative {
                sources,
                items,
                folder,
                max_size,
            } => self.pack_native(&sources, &items, folder.as_deref(), max_size),
        }
    }

    fn detect(
        &self,
        files: &[Candidate],
        public_path_prefix: Option<&str>,
    ) -> Result<Answer, Failure> {
        let found: Vec<Result<Detected, String>> = files
            .par_iter()
            .map(|file| {
                let path = Path::new(&file.path);
                Ok(Detected {
                    sourcemap: file.bundle && pair::has_sourcemap(path, public_path_prefix),
                    composed: file.map && pair::is_composed_map(path),
                    mapping: file.mapping && proguard::is_valid_mapping(&node::read(path)?),
                    native: file.native.then(|| native::magic_format(path)).flatten(),
                })
            })
            .collect();
        self.trace.mark("detect");

        let found: Vec<Detected> = found
            .into_iter()
            .collect::<Result<_, _>>()
            .map_err(Failure::failed)?;
        let indices = |pick: fn(&Detected) -> bool| {
            found
                .iter()
                .enumerate()
                .filter(|(_, file)| pick(file))
                .map(|(index, _)| index)
                .collect()
        };
        Ok(Answer::Detected {
            sourcemap: indices(|file| file.sourcemap),
            composed: indices(|file| file.composed),
            mapping: indices(|file| file.mapping),
            elf: indices(|file| file.native == Some(native::Format::Elf)),
            macho: indices(|file| file.native == Some(native::Format::Macho)),
        })
    }

    fn read_pairs(&mut self, paths: &[String], public_path_prefix: Option<&str>) -> Answer {
        let read: Vec<Result<SourcePair, Unreadable>> = paths
            .par_iter()
            .map(|path| pair::read_pair(Path::new(path), public_path_prefix))
            .collect();
        self.trace.mark("read pairs");

        let pairs = read
            .into_iter()
            .map(|result| match result {
                Ok(pair) => {
                    let answer = state(0, &pair);
                    let id = self.pairs.hold(pair);
                    PairAnswer::Read(PairState { id, ..answer })
                }
                Err(Unreadable::Skipped(skipped)) => PairAnswer::Skipped { skipped },
                Err(Unreadable::NoSourcemap) => PairAnswer::Missing(()),
            })
            .collect();
        Answer::Pairs { pairs }
    }

    fn inject(
        &mut self,
        ids: &[usize],
        mode: ReleaseMode,
        release_id: Option<&str>,
        now: u64,
    ) -> Result<Answer, Failure> {
        let mut pairs = self.pairs.take_all(ids)?;
        let now = uuid::Timestamp::from_unix(
            uuid::NoContext,
            now / MILLIS_PER_SECOND,
            (now % MILLIS_PER_SECOND) as u32 * NANOS_PER_MILLI,
        );

        let results: Vec<anyhow::Result<(Action, String, Vec<String>)>> = pairs
            .par_iter_mut()
            .map(|pair| {
                let mut warnings = Vec::new();
                let (action, chunk_id) = match mode {
                    ReleaseMode::Event => pair::inject_event_mode(pair, release_id, &mut warnings)?,
                    ReleaseMode::SymbolSet => pair::inject_symbol_set_mode(pair, release_id, &now)?,
                };
                Ok((action, chunk_id, warnings))
            })
            .collect();
        self.trace.mark("inject");

        let mut outcomes = Vec::with_capacity(results.len());
        let mut failure = None;
        for ((id, pair), result) in ids.iter().zip(&pairs).zip(results) {
            match result {
                Ok((action, chunk_id, warnings)) => outcomes.push(Outcome {
                    action,
                    chunk_id,
                    warnings,
                    pair: state(*id, pair),
                }),
                Err(error) => {
                    let message = format!("{}: {error:#}", pair.source_path.display());
                    failure.get_or_insert(Failure::failed(message));
                }
            }
        }
        self.pairs.put_back(ids, pairs);

        match failure {
            Some(failure) => Err(failure),
            None => Ok(Answer::Outcomes { outcomes }),
        }
    }

    // Unchanged pairs are written too, so every map ends in posthog-cli's canonical form.
    fn save(&mut self, ids: &[usize]) -> Result<Answer, Failure> {
        let pairs = self.pairs.take_all(ids)?;

        let staged: Vec<Result<Vec<write::Staged>, String>> = pairs
            .par_iter()
            .map(|pair| {
                let map = pair.map.serialize().map_err(|error| error.to_string())?;
                let source = write::stage(&pair.source_path, pair.source.as_bytes())?;
                match write::stage(&pair.map_path, &map) {
                    Ok(map) => Ok(vec![source, map]),
                    Err(message) => {
                        write::discard(&[source]);
                        Err(message)
                    }
                }
            })
            .collect();
        self.pairs.put_back(ids, pairs);
        self.trace.mark("stage");

        let mut files = Vec::with_capacity(staged.len() * 2);
        let mut failure = None;
        for result in staged {
            match result {
                Ok(pair) => files.extend(pair),
                Err(message) => {
                    failure.get_or_insert(message);
                }
            }
        }
        if let Some(message) = failure {
            write::discard(&files);
            return Err(Failure::failed(message));
        }

        write::commit(files, &self.trace).map_err(Failure::failed)?;
        Ok(Answer::Done {})
    }
}

impl Worker {
    fn fingerprint(&mut self, ids: &[usize]) -> Result<Answer, Failure> {
        let pairs = self.pairs.take_all(ids)?;

        let fingerprinted: Result<Vec<cleanup::Target>, String> =
            pairs.par_iter().map(cleanup::js_target).collect();
        self.pairs.put_back(ids, pairs);
        self.trace.mark("fingerprint");

        let targets = fingerprinted
            .map_err(Failure::failed)?
            .into_iter()
            .map(|target| self.targets.hold(target))
            .collect();
        Ok(Answer::Targets { targets })
    }

    fn set_release(
        &mut self,
        pairs: &[usize],
        maps: &[usize],
        release_id: Option<String>,
    ) -> Result<Answer, Failure> {
        let mut held_maps = self.maps.take_all(maps)?;
        let mut held_pairs = match self.pairs.take_all(pairs) {
            Ok(held) => held,
            Err(failure) => {
                self.maps.put_back(maps, held_maps);
                return Err(failure);
            }
        };

        let contents = held_pairs
            .iter_mut()
            .map(|pair| &mut pair.map)
            .chain(held_maps.iter_mut().map(|map| &mut map.content));
        for content in contents {
            content.release_id = release_id.clone();
        }

        self.pairs.put_back(pairs, held_pairs);
        self.maps.put_back(maps, held_maps);
        Ok(Answer::Done {})
    }

    fn prepare(
        &mut self,
        ids: &[usize],
        mode: ReleaseMode,
        folder: Option<&str>,
    ) -> Result<Answer, Failure> {
        let pairs = self.pairs.take_all(ids)?;
        let folder = folder.map(Path::new);
        let claimed = upload::claim(ids, pairs);

        let prepared: Result<Vec<upload::Prepared>, String> = claimed
            .ready
            .into_par_iter()
            .map(|(id, chunk_id, pair)| {
                let source_path = pair.source_path.clone();
                upload::prepare(id, chunk_id, pair, mode, folder)
                    .map_err(|error| format!("{}: {error:#}", source_path.display()))
            })
            .collect();
        self.trace.mark("prepare");

        Ok(Answer::Prepared {
            skipped: claimed.skipped,
            prepared: prepared.map_err(Failure::failed)?,
            duplicates: claimed.duplicates,
        })
    }

    fn css_candidates(&mut self, files: &[String], public_path_prefix: Option<&str>) -> Answer {
        let found: Vec<Option<cleanup::CssCandidate>> = files
            .par_iter()
            .map(|file| cleanup::css_candidate(file, public_path_prefix))
            .collect();
        self.trace.mark("css candidates");

        let candidates = found
            .into_iter()
            .map(|candidate| {
                let candidate = candidate?;
                let map_real_path = candidate.map_path().map(|path| {
                    display(&dunce::canonicalize(path).unwrap_or_else(|_| path.to_path_buf()))
                });
                Some(CssCandidateAnswer {
                    id: self.stylesheets.hold(candidate),
                    map_real_path,
                })
            })
            .collect();
        Answer::CssCandidates { candidates }
    }

    // Bundles first, then stylesheets, each in the order hog names them, which orders the warnings.
    fn clean_up(
        &mut self,
        targets: &[usize],
        css: &[usize],
        roots: &[String],
    ) -> Result<Answer, Failure> {
        let roots: Vec<PathBuf> = cleanup::canonical_roots(roots).map_err(Failure::failed)?;

        let mut warnings = Vec::new();
        let mut stylesheets = Vec::new();
        for id in css {
            let candidate = self.stylesheets.get(*id)?;
            match cleanup::css_target(candidate, &roots) {
                Ok(target) => stylesheets.extend(target),
                Err(warning) => warnings.push(warning),
            }
        }
        let mut all = Vec::with_capacity(targets.len() + stylesheets.len());
        for id in targets {
            all.push(self.targets.get(*id)?);
        }
        all.extend(&stylesheets);

        let cleaned = cleanup::clean_up(&all).map_err(Failure::failed)?;
        self.trace.mark("clean up");

        warnings.extend(cleaned.warnings);
        Ok(Answer::Cleaned {
            deleted_maps: cleaned.deleted_maps,
            warnings,
        })
    }
}

impl Worker {
    fn load_maps(&mut self, paths: &[String]) -> Answer {
        let loaded: Vec<Result<hermes::MapFile, String>> = paths
            .par_iter()
            .map(|path| hermes::load(Path::new(path)))
            .collect();
        self.trace.mark("load maps");

        let maps = loaded
            .into_iter()
            .map(|result| match result {
                Ok(map) => {
                    let answer = map_state(0, &map);
                    let id = self.maps.hold(map);
                    MapAnswer::Loaded(MapState { id, ..answer })
                }
                Err(unreadable) => MapAnswer::Unreadable { unreadable },
            })
            .collect();
        Answer::Maps { maps }
    }

    fn clone_metadata(&mut self, from: usize, to: usize) -> Result<Answer, Failure> {
        let mut composed = self.maps.take(to)?;

        let cloned = self
            .maps
            .get(from)
            .map(|packager| hermes::clone_metadata(&packager.content, &mut composed.content));
        let map = map_state(to, &composed);
        self.maps.put_back(&[to], vec![composed]);

        cloned.map(|()| Answer::Map { map })
    }

    // Every map or none, like `save`, so the two maps of a clone never disagree on the release.
    fn write_maps(&mut self, ids: &[usize]) -> Result<Answer, Failure> {
        let mut staged = Vec::with_capacity(ids.len());
        for id in ids {
            match self.maps.get(*id).map(hermes::MapFile::stage) {
                Ok(Ok(file)) => staged.push(file),
                Ok(Err(message)) => {
                    write::discard(&staged);
                    return Err(Failure::failed(message));
                }
                Err(failure) => {
                    write::discard(&staged);
                    return Err(failure);
                }
            }
        }

        write::commit(staged, &self.trace).map_err(Failure::failed)?;
        self.trace.mark("write maps");
        Ok(Answer::Done {})
    }

    fn prepare_maps(&mut self, ids: &[usize], folder: Option<&str>) -> Result<Answer, Failure> {
        let maps = self.maps.take_all(ids)?;
        let folder = folder.map(Path::new);

        let mut skipped = Vec::new();
        let mut ready = Vec::new();
        for (id, map) in ids.iter().zip(maps) {
            match hermes::upload_id(&map) {
                Ok(chunk_id) => ready.push((*id, chunk_id, map)),
                Err(reason) => skipped.push(upload::Skipped { id: *id, reason }),
            }
        }

        let prepared: Result<Vec<upload::Prepared>, String> = ready
            .into_par_iter()
            .map(|(id, chunk_id, map)| {
                let path = map.path.clone();
                hermes::prepare(id, chunk_id, map, folder)
                    .map_err(|error| format!("{}: {error:#}", path.display()))
            })
            .collect();
        self.trace.mark("prepare maps");

        Ok(Answer::Prepared {
            skipped,
            prepared: prepared.map_err(Failure::failed)?,
            duplicates: Vec::new(),
        })
    }
}

impl Worker {
    fn native_candidates(&mut self, paths: &[String]) -> Answer {
        let parsed: Vec<Result<Vec<native::Candidate>, String>> = paths
            .par_iter()
            .map(|path| guard::guarded(|| native::candidates(Path::new(path))))
            .collect();
        self.trace.mark("native candidates");

        let files = parsed
            .into_iter()
            .map(|result| match result {
                Ok(candidates) => NativeFileAnswer::Parsed {
                    candidates: candidates
                        .into_iter()
                        .map(|candidate| match candidate {
                            native::Candidate::Problem(problem) => {
                                CandidateAnswer::Problem { problem }
                            }
                            native::Candidate::Valid { debug_id, binary } => {
                                CandidateAnswer::Valid {
                                    debug_id,
                                    format: binary.format(),
                                    size: binary.size(),
                                    id: self.binaries.hold(binary),
                                }
                            }
                        })
                        .collect(),
                },
                Err(unparseable) => NativeFileAnswer::Unparseable { unparseable },
            })
            .collect();
        Answer::NativeFiles { files }
    }

    fn dsym_slices(&mut self, paths: &[String]) -> Answer {
        let read: Vec<Result<Vec<dsym::Slice>, String>> = paths
            .par_iter()
            .map(|path| guard::guarded(|| dsym::slices(Path::new(path))))
            .collect();
        self.trace.mark("dsym slices");

        let members = read
            .into_iter()
            .map(|result| match result {
                Ok(slices) => DsymMemberAnswer::Read {
                    slices: slices
                        .into_iter()
                        .map(|slice| SliceAnswer {
                            uuid: slice.uuid,
                            id: self.binaries.hold(slice.binary),
                        })
                        .collect(),
                },
                Err(unreadable) => DsymMemberAnswer::Unreadable { unreadable },
            })
            .collect();
        Answer::DsymMembers { members }
    }

    fn source_paths(&self, ids: &[usize]) -> Result<Answer, Failure> {
        let binaries: Vec<&native::Binary> = ids
            .iter()
            .map(|id| self.binaries.get(*id))
            .collect::<Result<_, _>>()?;

        let sources = binaries
            .par_iter()
            .map(|binary| {
                match guard::guarded(|| binary.source_paths().map_err(|error| format!("{error:#}")))
                {
                    Ok(paths) => SourcePathsAnswer::Found { paths },
                    Err(failed) => SourcePathsAnswer::Failed { failed },
                }
            })
            .collect();
        self.trace.mark("source paths");

        Ok(Answer::SourcePaths { sources })
    }

    // A dSYM symbol set that fits wins over a native file with its UUID, so a native file that shares
    // a dSYM's UUID packs only after it, and only when the dSYM does not fit. Its sources are still
    // read, for the warnings.
    fn pack_native(
        &mut self,
        sources: &[Vec<String>],
        items: &[PackItem],
        folder: Option<&str>,
        max_size: usize,
    ) -> Result<Answer, Failure> {
        let folder = folder.map(Path::new);
        if let Some(item) = items
            .iter()
            .find(|item| item.sources.is_some_and(|place| place >= sources.len()))
        {
            let message = format!("binary {} names a source list that is not there", item.id);
            return Err(Failure::bad_request(message));
        }
        let ids: Vec<usize> = items.iter().map(|item| item.id).collect();
        let binaries = self.binaries.take_all(&ids)?;
        // A binary hog left out, such as the smaller of two with one debug ID, is never packed.
        self.binaries.release_all();

        let dsym_ids: HashSet<&str> = items
            .iter()
            .filter(|item| item.bundle.is_some())
            .map(|item| item.chunk_id.as_str())
            .collect();
        let waits: Vec<bool> = items
            .iter()
            .map(|item| item.bundle.is_none() && dsym_ids.contains(item.chunk_id.as_str()))
            .collect();

        let mut groups: BTreeMap<Option<usize>, Vec<usize>> = (0..sources.len())
            .map(|place| (Some(place), Vec::new()))
            .collect();
        for (index, item) in items.iter().enumerate() {
            groups.entry(item.sources).or_default().push(index);
        }
        let pack_group = |place: Option<usize>, indexes: &[usize]| {
            let (files, unreadable) = match place {
                Some(place) => {
                    let (files, unreadable) = sources::collect(&sources[place]);
                    (Some(files), Some(unreadable))
                }
                None => (None, None),
            };
            let packed: Vec<(usize, Result<upload::Container, String>)> = indexes
                .par_iter()
                .map(|&index| {
                    let packed = native::pack(&binaries[index], files.as_ref(), folder)
                        .map_err(|error| format!("{error:#}"));
                    (index, packed)
                })
                .collect();
            (place.zip(unreadable), packed)
        };

        let mut unreadable: Vec<Option<Vec<sources::Unreadable>>> =
            (0..sources.len()).map(|_| None).collect();
        let mut first: Vec<Option<Result<upload::Container, String>>> =
            (0..items.len()).map(|_| None).collect();
        let packed: Vec<_> = groups
            .par_iter()
            .filter_map(|(&place, indexes)| {
                let ready: Vec<usize> = indexes
                    .iter()
                    .copied()
                    .filter(|&index| !waits[index])
                    .collect();
                (!ready.is_empty()).then(|| pack_group(place, &ready))
            })
            .collect();
        for (list, packed) in packed {
            if let Some((place, list)) = list {
                unreadable[place] = Some(list);
            }
            for (index, packed) in packed {
                first[index] = Some(packed);
            }
        }

        // As posthog-cli does, a dSYM bundle that fails to pack is skipped whole and leaves a native
        // file with its UUID to upload, while a native file that fails stops the request.
        let mut failed_bundles: HashMap<usize, String> = HashMap::new();
        for (item, packed) in items.iter().zip(&first) {
            match (item.bundle, packed) {
                (Some(bundle), Some(Err(message))) => {
                    failed_bundles
                        .entry(bundle)
                        .or_insert_with(|| message.clone());
                }
                (None, Some(Err(message))) => return Err(Failure::failed(message)),
                _ => {}
            }
        }
        let fitting: HashSet<&str> = items
            .iter()
            .zip(&first)
            .filter(|(item, _)| {
                item.bundle
                    .is_some_and(|bundle| !failed_bundles.contains_key(&bundle))
            })
            .filter_map(|(item, packed)| match packed {
                Some(Ok(packed)) if packed.size <= max_size => Some(item.chunk_id.as_str()),
                _ => None,
            })
            .collect();

        // A list that only waiting binaries read is still read, for its warnings.
        let packed: Vec<_> = groups
            .par_iter()
            .filter_map(|(&place, indexes)| {
                let late: Vec<usize> = indexes
                    .iter()
                    .copied()
                    .filter(|&index| {
                        waits[index] && !fitting.contains(items[index].chunk_id.as_str())
                    })
                    .collect();
                let unread = place.is_some_and(|place| unreadable[place].is_none());
                (unread || !late.is_empty()).then(|| pack_group(place, &late))
            })
            .collect();
        for (list, packed) in packed {
            if let Some((place, list)) = list {
                unreadable[place].get_or_insert(list);
            }
            for (index, packed) in packed {
                first[index] = Some(packed);
            }
        }
        self.trace.mark("pack native");

        let containers: Vec<Option<Packed>> = items
            .iter()
            .zip(first)
            .map(|(item, packed)| {
                if let Some(message) = item.bundle.and_then(|bundle| failed_bundles.get(&bundle)) {
                    return Ok(Some(Packed::Failed {
                        failed: message.clone(),
                    }));
                }
                packed
                    .transpose()
                    .map(|packed| packed.map(Packed::Container))
            })
            .collect::<Result<_, _>>()
            .map_err(Failure::failed)?;

        Ok(Answer::Packed {
            unreadable: unreadable
                .into_iter()
                .map(Option::unwrap_or_default)
                .collect(),
            containers,
        })
    }
}

fn send(message: &impl Serialize) -> io::Result<()> {
    let mut line = serde_json::to_vec(message)?;
    line.push(b'\n');

    let mut stdout = io::stdout().lock();
    stdout.write_all(&line)?;
    stdout.flush()
}

fn main() -> io::Result<()> {
    memory::tune_allocator();
    guard::install_hook();

    send(&Hello {
        r#type: "hello",
        protocol: PROTOCOL,
        version: env!("CARGO_PKG_VERSION"),
    })?;

    let mut worker = Worker {
        pairs: Store::new("pair"),
        maps: Store::new("map"),
        binaries: Store::new("binary"),
        targets: Store::new("cleanup target"),
        stylesheets: Store::new("stylesheet"),
        trace: Trace::from_environment(),
    };
    for line in io::stdin().lock().lines() {
        let response = serde_json::from_str::<Request>(&line?)
            .map_err(Failure::bad_request)
            .and_then(|request| worker.handle(request));

        send(&match response {
            Ok(result) => Response::Ok { ok: true, result },
            Err(error) => Response::Failed { ok: false, error },
        })?;
    }
    Ok(())
}
