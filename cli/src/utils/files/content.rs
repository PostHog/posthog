use anyhow::{Context, Result};
use sha2::Digest;
use std::path::PathBuf;

use crate::sourcemaps::content::SourceMapContent;

pub struct SourceFile<T: SourceContent> {
    pub path: PathBuf,
    pub content: T,
}

impl<T: SourceContent> SourceFile<T> {
    pub fn new(path: PathBuf, content: T) -> Self {
        SourceFile { path, content }
    }

    pub fn load(path: &PathBuf) -> Result<Self> {
        let content = std::fs::read(path)?;
        Ok(SourceFile::new(path.clone(), T::parse(content)?))
    }

    // TODO - I'm fairly sure the `dest` is redundant if it's None
    pub fn save(&self, dest: Option<PathBuf>) -> Result<()> {
        let final_path = dest.unwrap_or(self.path.clone());
        std::fs::write(&final_path, &self.content.serialize()?)?;
        Ok(())
    }
}

pub trait SourceContent {
    fn parse(content: Vec<u8>) -> Result<Self>
    where
        Self: Sized;

    fn serialize(&self) -> Result<Vec<u8>>;
}

impl SourceContent for String {
    fn parse(content: Vec<u8>) -> Result<Self> {
        Ok(String::from_utf8(content)?)
    }

    fn serialize(&self) -> Result<Vec<u8>> {
        Ok(self.clone().into_bytes())
    }
}

impl SourceContent for SourceMapContent {
    fn parse(content: Vec<u8>) -> Result<Self> {
        Ok(serde_json::from_slice(&content)?)
    }

    fn serialize(&self) -> Result<Vec<u8>> {
        Ok(serde_json::to_vec(self)?)
    }
}

impl SourceContent for Vec<u8> {
    fn parse(content: Vec<u8>) -> Result<Self> {
        Ok(content)
    }

    fn serialize(&self) -> Result<Vec<u8>> {
        Ok(self.clone())
    }
}

pub fn delete_files(paths: Vec<PathBuf>) -> Result<()> {
    // Delete local sourcemaps files from the sourcepair
    for path in paths {
        if path.exists() {
            std::fs::remove_file(&path)
                .context(format!("Failed to delete file: {}", path.display()))?;
        }
    }
    Ok(())
}

// TODO - find a better home for this - it's not really a "file" operation,
// but dumping it in the general "utils" feels gross
pub fn content_hash<Iter, Item: AsRef<[u8]>>(upload_data: Iter) -> String
where
    Iter: IntoIterator<Item = Item>,
{
    let mut hasher = sha2::Sha512::new();
    for data in upload_data {
        hasher.update(data.as_ref());
    }
    format!("{:x}", hasher.finalize())
}
