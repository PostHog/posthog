import sys
from pathlib import Path

# Add support-sidebar-max to Python path
ee_path = Path(__file__).parents[2] / "ee"
sys.path.append(str(ee_path))
