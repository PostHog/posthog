import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY")
API_ENDPOINT = os.getenv("ANTHROPIC_API_ENDPOINT")
MODEL = os.getenv("ANTHROPIC_MODEL")
GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")

# Validate required environment variables
required_vars = ["ANTHROPIC_API_KEY", "GITHUB_ACCESS_TOKEN"]
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    raise OSError(f"Missing required environment variables: {', '.join(missing_vars)}")
