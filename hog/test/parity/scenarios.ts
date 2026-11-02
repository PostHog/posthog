import { readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'

import type { Scenario, StoredObject } from './fake-server'
import { GIT_REPO, mappingOfSize, readTree, SMALL_MAPPING, write } from './fixtures'
import { EXPO_BUILD, HERMES_BUILD, HERMES_BUNDLES } from './hermes-fixtures'
import { bundles, EDGE_CASES, MALFORMED_MAP_DEBUG_ID, PUBLIC_PATH, STYLESHEET_LOOKUP, STYLESHEETS } from './js-fixtures'
import { INFO_PLIST_BINARY, INFO_PLIST_SETTINGS, INFO_PLIST_XML, XCODE_SETTINGS } from './plist-fixtures'
import { decodeFile, type ParityResult } from './run'
import { SYMBOL_SETS } from './symbol-set-fixtures'

type Files = Record<string, string | Uint8Array>

export interface ParityScenario {
    name: string
    server: Scenario
    files: () => Files
    rust: string[]
    hog: string[]
    // Commands to run first, against the same folder and server. Only the main command is recorded.
    before?: { rust: string[]; hog: string[] }[]
    // Run this many times against the same server and compare only the last run, to cover re-uploads.
    runs?: number
    // Also compare the files the run changed.
    snapshot?: boolean
    // Keep whole files in the golden, even large ones, because another scenario starts from them.
    fullSnapshot?: boolean
    // The run mints random UUIDv7 chunk ids, so compare their positions and not their values.
    randomIds?: boolean
    // Runs before the commands, for state outside the folder.
    setup?: () => void
    // Symbol sets the fake server stores for download.
    objects?: () => StoredObject[]
    // Variables both CLIs get on top of the credentials, like the build settings Xcode exports.
    env?: Record<string, string>
}

// The files posthog-cli left behind in another scenario: its inputs with the golden's changes.
function filesFrom(name: string): () => Files {
    return () => {
        const scenario = SCENARIOS.find((candidate) => candidate.name === name)!
        const golden = JSON.parse(
            readFileSync(join(import.meta.dir, 'golden', 'e2e', `${name}.json`), 'utf8')
        ) as ParityResult
        const files: Files = { ...scenario.files() }
        for (const [path, text] of Object.entries(golden.files ?? {})) {
            if (text === null) {
                delete files[path]
            } else {
                files[path] = decodeFile(text)
            }
        }
        return files
    }
}

const release = ['--release-name', 'com.example.app', '--release-version', '1.0', '--build', '7']

const proguard = (
    name: string,
    server: Scenario,
    options: Partial<ParityScenario> & { args?: string[]; file?: string } = {}
): ParityScenario => {
    const file = options.file ?? 'mapping.txt'
    const args = options.args ?? []
    return {
        name: `proguard-${name}`,
        server,
        files: options.files ?? (() => ({ [file]: SMALL_MAPPING })),
        rust: ['proguard', 'upload', '--path', file, '--map-id', `map-${name}`, ...args],
        hog: ['error-tracking', 'upload', file, '--map-id', `map-${name}`, ...args],
        runs: options.runs,
    }
}

export const SCENARIOS: ParityScenario[] = [
    proguard('fresh', 'fresh', { args: release }),
    proguard('no-release', 'fresh'),
    proguard('release-from-git', 'fresh', {
        file: 'app/mapping.txt',
        files: () => ({ ...GIT_REPO, 'app/mapping.txt': SMALL_MAPPING }),
    }),
    proguard('already-present', 'fresh', { args: release, runs: 2 }),
    proguard('post-only', 'post-only', { args: release }),
    proguard('hash-mismatch', 'hash-mismatch', { args: release }),
    proguard('hash-mismatch-force', 'hash-mismatch', { args: [...release, '--force'] }),
    proguard('hash-mismatch-skip', 'hash-mismatch', { args: [...release, '--skip-on-conflict'] }),
    proguard('release-mismatch', 'release-mismatch', { args: release }),
    proguard('check-403', 'check-403', { args: release }),
    proguard('start-500-once', 'start-500-once', { args: release }),
    proguard('block-multiple', 'fresh', { files: () => ({ 'mapping.txt': mappingOfSize(2 * 128 * 1024) }) }),
    proguard('bom-crlf', 'fresh', {
        files: () => ({ 'mapping.txt': `\uFEFF${SMALL_MAPPING.replaceAll('\n', '\r\n')}` }),
    }),
]

type JsCommand = 'inject' | 'upload' | 'process'

// posthog-cli's `sourcemap <command> -d <path>` and hog's `error-tracking <command> <path>` take the
// same flags after the path.
const jsArgs = (command: JsCommand, path: string, args: string[]): { rust: string[]; hog: string[] } => ({
    rust: ['sourcemap', command, '-d', path, ...args],
    hog: ['error-tracking', command, path, ...args],
})

const js = (
    name: string,
    command: JsCommand,
    files: () => Files,
    options: Partial<Omit<ParityScenario, 'before'>> & {
        args?: string[]
        path?: string
        before?: [JsCommand, string[]][]
    } = {}
): ParityScenario => ({
    name: `js-${name}`,
    server: options.server ?? 'fresh',
    files,
    ...jsArgs(command, options.path ?? '.', options.args ?? []),
    before: options.before?.map(([step, args]) => jsArgs(step, options.path ?? '.', args)),
    runs: options.runs,
    snapshot: options.snapshot ?? true,
    fullSnapshot: options.fullSnapshot,
    randomIds: options.randomIds,
})

const jsRelease = ['--release-name', 'web', '--release-version', '2.1.0']
const symbolSet = ['--release-mode', 'symbol-set']

SCENARIOS.push(
    js('inject-bundles', 'inject', bundles),
    js('inject-edge-cases', 'inject', () => EDGE_CASES),
    js('inject-twice', 'inject', () => EDGE_CASES, { runs: 2 }),
    js('inject-malformed-map-debug-id', 'inject', () => MALFORMED_MAP_DEBUG_ID),
    js('inject-release', 'inject', bundles, { args: jsRelease }),
    js('inject-release-from-git', 'inject', () => ({ ...GIT_REPO, ...bundles() })),
    js('inject-release-change', 'inject', bundles, {
        args: ['--release-name', 'web', '--release-version', '2.2.0'],
        before: [['inject', jsRelease]],
    }),
    js('inject-public-path', 'inject', () => PUBLIC_PATH, { args: ['--public-path-prefix', '/static/js'] }),
    js('inject-info-plist', 'inject', () => ({ ...bundles(), 'Info.plist': INFO_PLIST_XML }), {
        args: ['--info-plist', 'Info.plist'],
    }),
    js('inject-file-root', 'inject', bundles, { path: 'esbuild-cjs/index.cjs' }),
    js('process-bundles', 'process', bundles, { args: jsRelease }),
    js('process-no-release', 'process', bundles),
    js('process-edge-cases', 'process', () => EDGE_CASES, { args: jsRelease }),
    js('process-already-present', 'process', bundles, { args: jsRelease, runs: 2 }),
    js('process-hash-mismatch', 'process', bundles, {
        args: [...jsRelease, '--skip-on-conflict'],
        server: 'hash-mismatch',
    }),
    js('process-release-mismatch', 'process', bundles, { args: jsRelease, server: 'release-mismatch' }),
    js('process-post-only', 'process', bundles, { args: jsRelease, server: 'post-only' }),
    js('process-delete-after', 'process', () => ({ ...STYLESHEETS, ...bundles() }), {
        args: [...jsRelease, '--delete-after'],
    }),
    js('process-delete-after-css-lookup', 'process', () => STYLESHEET_LOOKUP, {
        args: [...jsRelease, '--delete-after', '--public-path-prefix', 'https://cdn.example.com/assets'],
    }),
    js('upload-native-debug-ids', 'upload', bundles),
    js('upload-after-inject', 'upload', bundles, { before: [['inject', jsRelease]] }),
    js('upload-not-injected', 'upload', () => EDGE_CASES),
    js('inject-symbol-set', 'inject', bundles, {
        args: [...jsRelease, ...symbolSet],
        randomIds: true,
        fullSnapshot: true,
    }),
    js('upload-symbol-set', 'upload', filesFrom('js-inject-symbol-set'), { args: [...jsRelease, ...symbolSet] }),
    js('upload-symbol-set-new-release', 'upload', filesFrom('js-inject-symbol-set'), {
        args: ['--release-name', 'web', '--release-version', '3.0.0', ...symbolSet],
    }),
    js('upload-symbol-set-hash-mismatch', 'upload', filesFrom('js-inject-symbol-set'), {
        args: [...jsRelease, ...symbolSet, '--skip-on-conflict'],
        server: 'hash-mismatch',
    })
)

// posthog-cli's `hermes inject|clone|upload` and the hog commands that replace them.
const hermesArgs = {
    inject: (path: string, args: string[] = []) => ({
        rust: ['hermes', 'inject', '-d', path, ...args],
        hog: ['error-tracking', 'inject', path, ...args],
    }),
    clone: (from: string, to: string, args: string[] = []) => ({
        rust: ['hermes', 'clone', '-m', from, '-c', to, ...args],
        hog: ['error-tracking', 'clone', from, to, ...args],
    }),
    upload: (path: string, args: string[] = []) => ({
        rust: ['hermes', 'upload', '-d', path, ...args],
        hog: ['error-tracking', 'upload', path, ...args],
    }),
}

const hermes = (
    name: string,
    step: { rust: string[]; hog: string[] },
    files: () => Files,
    options: Partial<ParityScenario> = {}
): ParityScenario => ({ name: `hermes-${name}`, server: 'fresh', files, ...step, snapshot: true, ...options })

const ANDROID_MAP = 'android/index.android.bundle.map'
const ANDROID_COMPOSED = 'android/hbc/index.android.bundle.hbc.composed.map'
const appRelease = ['--release-name', 'com.example.app', '--release-version', '1.4.0', '--build', '42']

SCENARIOS.push(
    hermes('inject', hermesArgs.inject('.'), () => HERMES_BUNDLES),
    hermes('inject-twice', hermesArgs.inject('.'), () => HERMES_BUNDLES, { runs: 2 }),
    hermes('inject-symbol-set', hermesArgs.inject('.', [...appRelease, ...symbolSet]), () => HERMES_BUNDLES, {
        randomIds: true,
    }),
    hermes('clone', hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED), () => HERMES_BUILD, {
        before: [hermesArgs.inject('android')],
    }),
    hermes(
        'clone-symbol-set',
        hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED, [...appRelease, ...symbolSet]),
        () => HERMES_BUILD,
        {
            before: [hermesArgs.inject('android')],
        }
    ),
    hermes(
        'clone-symbol-set-keeps-release',
        hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED, symbolSet),
        () => HERMES_BUILD,
        {
            before: [hermesArgs.inject('android', [...appRelease, ...symbolSet])],
            randomIds: true,
        }
    ),
    hermes(
        'clone-debug-id',
        hermesArgs.clone('ios/main.jsbundle.map', 'ios/hbc/main.jsbundle.hbc.composed.map'),
        () => EXPO_BUILD
    ),
    hermes('upload', hermesArgs.upload('android/hbc', appRelease), () => HERMES_BUILD, {
        before: [hermesArgs.inject('android'), hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED)],
    }),
    hermes('upload-from-git', hermesArgs.upload('android/hbc'), () => ({ ...GIT_REPO, ...HERMES_BUILD }), {
        before: [hermesArgs.inject('android'), hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED)],
    }),
    hermes('upload-symbol-set', hermesArgs.upload('android/hbc', [...appRelease, ...symbolSet]), () => HERMES_BUILD, {
        before: [
            hermesArgs.inject('android'),
            hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED, [...appRelease, ...symbolSet]),
        ],
    }),
    hermes('upload-already-present', hermesArgs.upload('android/hbc', appRelease), () => HERMES_BUILD, {
        before: [hermesArgs.inject('android'), hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED)],
        runs: 2,
    }),
    hermes(
        'upload-hash-mismatch',
        hermesArgs.upload('android/hbc', [...appRelease, ...symbolSet, '--skip-on-conflict']),
        () => HERMES_BUILD,
        {
            server: 'hash-mismatch',
            before: [hermesArgs.inject('android'), hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED)],
        }
    ),
    hermes(
        'upload-release-mismatch',
        hermesArgs.upload('android/hbc', [...appRelease, ...symbolSet]),
        () => HERMES_BUILD,
        {
            server: 'release-mismatch',
            before: [hermesArgs.inject('android'), hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED)],
        }
    ),
    hermes('upload-post-only', hermesArgs.upload('android/hbc', appRelease), () => HERMES_BUILD, {
        server: 'post-only',
        before: [hermesArgs.inject('android'), hermesArgs.clone(ANDROID_MAP, ANDROID_COMPOSED)],
    }),
    hermes('upload-debug-id', hermesArgs.upload('ios/hbc', appRelease), () => EXPO_BUILD, {
        before: [hermesArgs.clone('ios/main.jsbundle.map', 'ios/hbc/main.jsbundle.hbc.composed.map')],
    }),
    hermes('upload-no-chunk-id', hermesArgs.upload('android/hbc'), () => HERMES_BUILD)
)

// posthog-cli's `symbol-sets upload`, which takes ELF files, Mach-O files and dSYM bundles in one
// folder, and `hog error-tracking upload`. native/build.sh builds the binaries.
const linux = (): Files => readTree(join(import.meta.dir, 'native', 'bin', 'linux'), 'linux')
const apple = (): Files => readTree(join(import.meta.dir, 'native', 'bin', 'apple'), 'apple')
const appleLoose = (): Files => readTree(join(import.meta.dir, 'native', 'bin', 'apple-loose'), 'apple-loose')

const native = (
    name: string,
    path: string,
    files: () => Files,
    options: Partial<ParityScenario> & { args?: string[] } = {}
): ParityScenario => ({
    name: `native-${name}`,
    server: 'fresh',
    files,
    rust: ['symbol-sets', 'upload', '-d', path, ...(options.args ?? [])],
    hog: ['error-tracking', 'upload', path, ...(options.args ?? [])],
    ...options,
})

const nativeRelease = ['--release-name', 'shop', '--release-version', '3.2.0']

SCENARIOS.push(
    native('linux', 'linux', linux),
    native('linux-release', 'linux', linux, { args: nativeRelease }),
    native('apple', 'apple', apple, { args: nativeRelease }),
    native('dsym-root', 'apple/Shop.app.dSYM', apple),
    native('macho-loose', 'apple-loose', appleLoose, { args: nativeRelease }),
    native('mixed-from-git', '.', () => ({ ...GIT_REPO, ...linux(), ...apple() })),
    native('already-present', '.', () => ({ ...linux(), ...apple() }), { args: nativeRelease, runs: 2 }),
    native('hash-mismatch', '.', () => ({ ...linux(), ...apple() }), {
        args: [...nativeRelease, '--skip-on-conflict'],
        server: 'hash-mismatch',
    }),
    native('hash-mismatch-force', 'linux', linux, { args: [...nativeRelease, '--force'], server: 'hash-mismatch' }),
    native('post-only', 'linux', linux, { args: nativeRelease, server: 'post-only' }),
    native('release-mismatch', 'apple', apple, { args: nativeRelease, server: 'release-mismatch' }),
    native('only-unusable', 'linux/checkout-no-build-id', linux)
)

// The native fixtures' DWARF names sources under this folder, which `--include-source` reads.
const NATIVE_SOURCES = '/tmp/hog-parity-native'
const placeSources = (): void => {
    rmSync(NATIVE_SOURCES, { recursive: true, force: true })
    write(NATIVE_SOURCES, readTree(join(import.meta.dir, 'native', 'src')))
}
const removeSources = (): void => rmSync(NATIVE_SOURCES, { recursive: true, force: true })
const withSources = ['--include-source', ...nativeRelease]

SCENARIOS.push(
    native('sources-linux', 'linux', linux, { args: withSources, setup: placeSources }),
    native('sources-apple', 'apple', apple, { args: withSources, setup: placeSources }),
    native('sources-loose', 'apple-loose', appleLoose, { args: withSources, setup: placeSources }),
    native('sources-skip-on-conflict', 'linux', linux, {
        args: [...withSources, '--skip-on-conflict'],
        server: 'hash-mismatch',
        setup: placeSources,
    }),
    native('sources-missing', '.', () => ({ ...linux(), ...apple() }), { args: withSources, setup: removeSources })
)

// `posthog-cli release resolve --json` and `hog error-tracking release` send the same requests.
const releaseScenario = (name: string, args: string[], files: () => Files = () => ({})): ParityScenario => ({
    name: `release-${name}`,
    server: 'fresh',
    files,
    rust: ['release', 'resolve', '--json', ...args],
    hog: ['error-tracking', 'release', ...args],
})

// `posthog-cli symbol-sets extract|download` and the hog commands write the same files.
const extract = (file: string): ParityScenario => ({
    name: `extract-${file.replaceAll('.', '-')}`,
    server: 'fresh',
    files: () => SYMBOL_SETS,
    rust: ['symbol-sets', 'extract', file, '-o', 'out'],
    hog: ['error-tracking', 'extract', file, '--output-dir', 'out'],
    snapshot: true,
})

const STORED = (): StoredObject[] => [
    {
        id: '0192f0a0-0000-7000-8000-00000000000a',
        ref: 'static/chunks/app.js.map',
        data: SYMBOL_SETS['app.js.map.bin']!,
    },
    { id: '0192f0a0-0000-7000-8000-00000000000b', ref: 'Shop.dSYM', data: SYMBOL_SETS['Shop.dSYM']! },
    // A chunk ID is a ref that looks like a symbol set ID.
    {
        id: '0192f0a0-0000-7000-8000-00000000000c',
        ref: '3f161e6c-fc03-5fe2-a9e9-08e5ae65fd15',
        data: SYMBOL_SETS['app.js.map.bin']!,
    },
]

const download = (name: string, rust: string[], hog: string[]): ParityScenario => ({
    name: `download-${name}`,
    server: 'fresh',
    files: () => ({}),
    rust: ['symbol-sets', 'download', ...rust, '-o', 'out'],
    hog: ['error-tracking', 'download', ...hog, '--output-dir', 'out'],
    snapshot: true,
    objects: STORED,
})

SCENARIOS.push(
    releaseScenario('flags', ['--release-name', 'web', '--release-version', '2.1.0', '--build', '9']),
    releaseScenario('from-git', [], () => GIT_REPO),
    releaseScenario('none', []),
    releaseScenario('info-plist-xml', ['--info-plist', 'Info.plist'], () => ({ 'Info.plist': INFO_PLIST_XML })),
    releaseScenario('info-plist-binary', ['--info-plist', 'Info.plist'], () => ({ 'Info.plist': INFO_PLIST_BINARY })),
    {
        ...releaseScenario('info-plist-build-settings', ['--info-plist', 'Info.plist'], () => ({
            'Info.plist': INFO_PLIST_SETTINGS,
        })),
        env: XCODE_SETTINGS,
    },
    releaseScenario('info-plist-flags-win', ['--info-plist', 'Info.plist', '--release-version', '9.9.9'], () => ({
        'Info.plist': INFO_PLIST_XML,
    })),
    releaseScenario('info-plist-missing', ['--info-plist', 'Missing.plist']),
    ...Object.keys(SYMBOL_SETS).map(extract),
    download('by-ref', ['--ref', 'static/chunks/app.js.map'], ['static/chunks/app.js.map']),
    download('by-id', ['--id', '0192f0a0-0000-7000-8000-00000000000b'], ['0192f0a0-0000-7000-8000-00000000000b']),
    download('dsym-by-ref', ['--ref', 'Shop.dSYM'], ['Shop.dSYM']),
    download(
        'uuid-shaped-ref',
        ['--ref', '3f161e6c-fc03-5fe2-a9e9-08e5ae65fd15'],
        ['3f161e6c-fc03-5fe2-a9e9-08e5ae65fd15', '--ref']
    ),
    download('unknown-ref', ['--ref', 'missing.js.map'], ['missing.js.map'])
)

// Real Xcode, Rust and React Native output from getsentry/symbolic, described in real/README.md.
const realApple = (): Files => readTree(join(import.meta.dir, 'real', 'apple'), 'apple')
const realReactNative = (): Files => readTree(join(import.meta.dir, 'real', 'react-native'), 'rn')
const realRelease = ['--release-name', 'com.example.app', '--release-version', '4.0.0']
const RN_MAP = 'rn/react-native-metro.js.map'
const RN_HERMES_MAP = 'rn/react-native-hermes.map'

SCENARIOS.push(
    native('real-dsyms', 'apple', realApple, { args: realRelease }),
    native('real-dsyms-sources', 'apple', realApple, { args: ['--include-source', ...realRelease] }),
    native('real-dsyms-hash-mismatch', 'apple', realApple, {
        args: [...realRelease, '--skip-on-conflict'],
        server: 'hash-mismatch',
    }),
    hermes('real-inject', hermesArgs.inject('rn'), realReactNative),
    hermes('real-inject-symbol-set', hermesArgs.inject('rn', [...realRelease, ...symbolSet]), realReactNative, {
        randomIds: true,
    }),
    hermes('real-clone', hermesArgs.clone(RN_MAP, RN_HERMES_MAP), realReactNative, {
        before: [hermesArgs.inject('rn')],
    }),
    hermes(
        'real-clone-symbol-set',
        hermesArgs.clone(RN_MAP, RN_HERMES_MAP, [...realRelease, ...symbolSet]),
        realReactNative,
        {
            before: [hermesArgs.inject('rn')],
        }
    )
)
