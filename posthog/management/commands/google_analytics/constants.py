"""Series of constants for accessing google analytics information"""
from datetime import datetime
import os

CREDENTIALS_FILE_PATH = os.getcwd() + '/scripts/google_analytics/client_secrets.json'
EVENT_NAME = '$pageview'
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = '2018-01-01'
VIEW_ID = "169512480"
GA_ID = f"ga:{VIEW_ID}"
METRICS = "ga:pageviews"
DIMENSIONS = "ga:date, ga:pagePath"
API_KEY = "PYbSt25buQK4Ksfpd4IBABOZ9vDO5LnKcgdHMyEJq7Y"
HOST = "http://localhost:8000"
