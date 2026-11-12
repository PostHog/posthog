"""Entry point for `python -I .github/scripts/dependency_proof/__main__.py identify|prove` from the repository root."""

import sys
from pathlib import Path

# `python -I` keeps the script directory off sys.path, so the package is added by hand.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dependency_proof.prove import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
