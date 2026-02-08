use std::path::PathBuf;

use anyhow::Result;
use globset::{Glob, GlobSet, GlobSetBuilder};
use walkdir::DirEntry;

pub struct FileSelection(Box<dyn Iterator<Item = DirEntry>>);

impl FileSelection {
    pub fn from_roots(files: Vec<PathBuf>) -> Self {
        Self(Box::new(files.into_iter().flat_map(|file| {
            walkdir::WalkDir::new(file)
                .into_iter()
                .filter_map(|entry| entry.ok())
        })))
    }

    pub fn include(mut self, include: Vec<String>) -> Result<Self> {
        if include.is_empty() {
            return Ok(self);
        }
        let include_set = build_glob_set(include)?;
        self.0 = Box::new(
            self.0
                .filter(move |entry| include_set.is_match(entry.path())),
        );
        Ok(self)
    }

    pub fn exclude(mut self, exclude: Vec<String>) -> Result<Self> {
        if exclude.is_empty() {
            return Ok(self);
        }
        let exclude_set = build_glob_set(exclude)?;
        self.0 = Box::new(
            self.0
                .filter(move |entry| !exclude_set.is_match(entry.path())),
        );
        Ok(self)
    }
}

impl IntoIterator for FileSelection {
    type Item = DirEntry;
    type IntoIter = Box<dyn Iterator<Item = DirEntry>>;
    fn into_iter(self) -> Self::IntoIter {
        self.0
    }
}

fn build_glob_set(patterns: Vec<String>) -> Result<GlobSet> {
    let mut builder = GlobSetBuilder::new();
    for glob in patterns.iter() {
        builder.add(Glob::new(glob)?);
    }
    let set: globset::GlobSet = builder.build()?;
    Ok(set)
}
