"""
Facade for cookie_banner.

The ONLY module other products or core are allowed to import.
"""

from ..remote_config import build_cookie_banner_site_app_js as build_cookie_banner_site_app_js

__all__ = ["build_cookie_banner_site_app_js"]
