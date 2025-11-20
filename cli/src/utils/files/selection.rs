use std::{fmt::Display, path::PathBuf};

use anyhow::{bail, Result};
use globset::{Glob, GlobSet, GlobSetBuilder};
use walkdir::DirEntry;

type FileFilter = Box<dyn Fn(&DirEntry) -> bool>;

pub struct FileSelection {
    directory: PathBuf,
    include: Vec<String>,
    exclude: Vec<String>,
    filters: Vec<FileFilter>,
}

impl Display for FileSelection {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.directory.display())
    }
}

impl FileSelection {
    pub fn new(directory: PathBuf, include: Vec<String>, exclude: Vec<String>) -> Self {
        FileSelection {
            directory,
            include,
            exclude,
            filters: Vec::new(),
        }
    }

    pub fn filter(mut self, filter: impl Fn(&DirEntry) -> bool + 'static) -> Self {
        self.filters.push(Box::new(filter));
        self
    }

    pub fn try_into_iter(self) -> Result<impl Iterator<Item = DirEntry>> {
        self.validate()?;
        let include_set = build_glob_set(self.include)?;
        let exclude_set = build_glob_set(self.exclude)?;
        let walker = walkdir::WalkDir::new(self.directory);
        let inner = walker
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(move |entry| {
                if let Some(include_set) = &include_set {
                    if !include_set.is_match(entry.path()) {
                        return false;
                    }
                }

                if let Some(exclude_set) = &exclude_set {
                    if exclude_set.is_match(entry.path()) {
                        return false;
                    }
                }

                for filter in &self.filters {
                    if !filter(entry) {
                        return false;
                    }
                }

                true
            });
        Ok(inner)
    }

    fn validate(&self) -> Result<()> {
        if !self.directory.exists() {
            bail!("Directory does not exist");
        }
        Ok(())
    }
}

fn build_glob_set(patterns: Vec<String>) -> Result<Option<GlobSet>> {
    if patterns.is_empty() {
        return Ok(None);
    }
    let mut builder = GlobSetBuilder::new();
    for glob in patterns.iter() {
        builder.add(Glob::new(glob)?);
    }
    let set: globset::GlobSet = builder.build()?;
    Ok(Some(set))
}
