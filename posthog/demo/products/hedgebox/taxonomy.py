# URLs

SITE_URL = "https://hedgebox.net"

URL_HOME = f"{SITE_URL}/"
URL_MARIUS_TECH_TIPS = f"{SITE_URL}/mariustechtips/"
URL_PRICING = f"{SITE_URL}/pricing/"

URL_SIGNUP = f"{SITE_URL}/signup/"
URL_LOGIN = f"{SITE_URL}/login/"
dyn_url_invite = lambda invite_id: f"{SITE_URL}/invite/{invite_id}/"

URL_FILES = f"{SITE_URL}/files/"
dyn_url_file = lambda file_id: f"{SITE_URL}/files/{file_id}/"

URL_ACCOUNT_SETTINGS = f"{SITE_URL}/account/settings/"
URL_ACCOUNT_BILLING = f"{SITE_URL}/account/billing/"
URL_ACCOUNT_TEAM = f"{SITE_URL}/account/team/"

URL_PRODUCT_AD_LINK_1 = f"https://shop.example.com/products/10ft-hedgehog-statue?utm_source=hedgebox&utm_medium=paid"
URL_PRODUCT_AD_LINK_2 = f"https://travel.example.com/cruise/hedge-watching?utm_source=hedgebox&utm_medium=paid"

# Event taxonomy

EVENT_SIGNED_UP = "signed_up"  # Properties: from_invite
EVENT_LOGGED_IN = "logged_in"  # No extra properties
EVENT_LOGGED_OUT = "logged_out"  # No extra properties

EVENT_UPLOADED_FILE = "uploaded_file"  # Properties: file_type, file_size_b
EVENT_DOWNLOADED_FILE = "downloaded_file"  # Properties: file_type, file_size_b
EVENT_DELETED_FILE = "deleted_file"  # Properties: file_type, file_size_b
EVENT_SHARED_FILE_LINK = "shared_file_link"  # Properties: file_type, file_size_b

EVENT_UPGRADED_PLAN = "upgraded_plan"  # Properties: previous_plan, new_plan
EVENT_DOWNGRADED_PLAN = "downgraded_plan"  # Properties: previous_plan, new_plan

EVENT_INVITED_TEAM_MEMBER = "invited_team_member"  # No extra properties
EVENT_REMOVED_TEAM_MEMBER = "removed_team_member"  # No extra properties

EVENT_PAID_BILL = "paid_bill"  # Properties: plan, amount_usd

# Group taxonomy

GROUP_TYPE_ACCOUNT = "account"  # Properties: name, industry, used_mb, file_count, plan, team_size

# Feature flags

FILE_PREVIEWS_FLAG_KEY = "file-previews"
NEW_SIGNUP_PAGE_FLAG_KEY = "signup-page-4.0"
NEW_SIGNUP_PAGE_FLAG_ROLLOUT_PERCENT = 50
PROPERTY_NEW_SIGNUP_PAGE_FLAG = f"$feature/{NEW_SIGNUP_PAGE_FLAG_KEY}"
SIGNUP_SUCCESS_RATE_TEST = 0.5794
SIGNUP_SUCCESS_RATE_CONTROL = 0.4887

# World properties

# How many clusters should be companies (made up of business users) as opposed to social circles (personal users)
COMPANY_CLUSTERS_PROPORTION = 0.2
