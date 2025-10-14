use anyhow::{Context, Result};
use sha2::Digest;
use std::path::PathBuf;

pub struct SourceFile {
    pub path: PathBuf,
    pub content: String,
}

impl SourceFile {
    pub fn new(path: PathBuf, content: String) -> Self {
        SourceFile { path, content }
    }

    pub fn load(path: &PathBuf) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        Ok(SourceFile::new(path.clone(), content))
    }

    pub fn save(&self, dest: Option<PathBuf>) -> Result<()> {
        let final_path = dest.unwrap_or(self.path.clone());
        std::fs::write(&final_path, &self.content)?;
        Ok(())
    }
}

fn delete_files(paths: Vec<PathBuf>) -> Result<()> {
    // Delete local sourcemaps files from the sourcepair
    for path in paths {
        if path.exists() {
            std::fs::remove_file(&path).context(format!(
                "Failed to delete sourcemaps file: {}",
                path.display()
            ))?;
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
