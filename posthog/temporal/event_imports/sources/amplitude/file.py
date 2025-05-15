import os
import gzip
import zipfile
import structlog
import requests
import shutil
from typing import List, Dict, Any, Optional


def extract_zip_file(zip_file_path: str, extract_dir: str) -> None:
    """
    Extracts a zip file to the specified directory.
    
    Args:
        zip_file_path: Path to the zip file
        extract_dir: Directory to extract the files to
    """
    os.makedirs(extract_dir, exist_ok=True)
    
    with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
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
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.gz'):
                gz_file_path = os.path.join(root, file)
                logger.info(f"Found gzipped file: {gz_file_path}")

                output_file_path = gz_file_path[:-3]

                with gzip.open(gz_file_path, 'rb') as gz_file, open(output_file_path, 'wb') as out_file:
                    out_file.write(gz_file.read())
                
                logger.info(f"Decompressed {gz_file_path} to {output_file_path}")
                os.remove(gz_file_path)


def find_files_to_process(directory: str) -> List[str]:
    """
    Finds all files to process in a directory or its immediate subdirectory.
    
    Args:
        directory: The directory to search in
        
    Returns:
        List of file paths to process
    """
    logger = structlog.get_logger()
    
    directory_contents = os.listdir(directory)
    
    file_paths = [os.path.join(directory, f) for f in directory_contents 
                if os.path.isfile(os.path.join(directory, f))]

    # If no files found directly but there's a subdirectory, check there
    if not file_paths and directory_contents and os.path.isdir(os.path.join(directory, directory_contents[0])):
        subdirectory = os.path.join(directory, directory_contents[0])
        
        subdirectory_contents = os.listdir(subdirectory)
        
        file_paths = [os.path.join(subdirectory, f) for f in subdirectory_contents 
                    if os.path.isfile(os.path.join(subdirectory, f))]
    
    logger.info(f"Found {len(file_paths)} files to process in {directory}")
    return file_paths


def send_event_batch(batch: List[Dict[str, Any]], posthog_api_key: str, posthog_domain: Optional[str] = None) -> int:
    """
    Sends a batch of events to PostHog.
    
    Args:
        batch: List of events to send
        posthog_api_key: PostHog API key
        posthog_domain: PostHog domain (defaults to 'https://app.dev.posthog.com')
        
    Returns:
        Number of events processed
    """
    if not batch:
        return 0
        
    logger = structlog.get_logger()
    
    url = f"{posthog_domain or 'https://app.dev.posthog.com'}/batch/"
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": posthog_api_key,
        "historical_migration": True,
        "batch": batch
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        if len(batch) > 1:
            logger.info(f"Sent batch of {len(batch)} events to PostHog. Status: {response.status_code}")
        else:
            logger.info(f"Sent final event to PostHog. Status: {response.status_code}")
            
        logger.debug(f"API response: {response.text[:200]}..." if len(response.text) > 200 else f"API response: {response.text}")
        return len(batch)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send batch to PostHog: {str(e)}")
        if hasattr(e, 'response') and e.response:
            logger.error(f"Response status: {e.response.status_code}, Response body: {e.response.text[:500]}")
        return 0


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
        logger.error(f"Failed to clean up temporary directory {directory}: {str(e)}")
