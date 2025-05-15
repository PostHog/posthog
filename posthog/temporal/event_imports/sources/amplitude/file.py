import os
import gzip
import zipfile
import shutil
import structlog


def extract_zip_file(zip_file_path: str, extract_dir: str) -> None:
    """
    Extracts a zip file to the specified directory.
    Args:
        zip_file_path: Path to the zip file
        extract_dir: Directory to extract the files to
    """
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)


def extract_gzipped_files(directory: str) -> None:
    """
    Walks through a directory and extracts any gzipped files found.
    Removes the original gzipped files after extraction.
    Args:
        directory: Directory to walk through
    """
    logger = structlog.get_logger()
    logger.info(f"Checking for gzipped files in {directory}")

    for root, _dirnames, files in os.walk(directory):
        for file in files:
            if file.endswith(".gz"):
                gz_file_path = os.path.join(root, file)
                logger.info(f"Found gzipped file: {gz_file_path}")

                output_file_path = gz_file_path[:-3]

                with gzip.open(gz_file_path, "rb") as gz_file, open(output_file_path, "wb") as out_file:
                    out_file.write(gz_file.read())

                logger.info(f"Decompressed {gz_file_path} to {output_file_path}")
                os.remove(gz_file_path)


def find_files_to_process(directory: str) -> list[str]:
    """
    Finds all files to process in a directory or its immediate subdirectory.
    Args:
        directory: The directory to search in
    Returns:
        List of file paths to process
    """
    logger = structlog.get_logger()

    directory_contents = os.listdir(directory)

    file_paths = [os.path.join(directory, f) for f in directory_contents if os.path.isfile(os.path.join(directory, f))]

    # If no files found directly but there's a subdirectory, check there
    if not file_paths and directory_contents and os.path.isdir(os.path.join(directory, directory_contents[0])):
        subdirectory = os.path.join(directory, directory_contents[0])

        subdirectory_contents = os.listdir(subdirectory)

        file_paths = [
            os.path.join(subdirectory, f)
            for f in subdirectory_contents
            if os.path.isfile(os.path.join(subdirectory, f))
        ]

    logger.info(f"Found {len(file_paths)} files to process in {directory}")
    return file_paths


def cleanup_temp_dir(directory: str) -> None:
    """
    Cleans up a temporary directory.
    Args:
        directory: Directory to clean up
    """
    try:
        shutil.rmtree(directory)
        shutil.rmtree(directory, ignore_errors=True)
    except Exception as e:
        logger = structlog.get_logger()
        logger.exception(f"Failed to clean up temporary directory {directory}: {str(e)}")
