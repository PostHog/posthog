import re

# Supabase's direct connection host (`db.<ref>.supabase.co`) is IPv6-only and so is
# unreachable from PostHog's IPv4 egress, unless the project has Supabase's IPv4 add-on.
SUPABASE_DIRECT_HOST_RE = re.compile(r"^db\.[a-z0-9]+\.supabase\.co$", re.IGNORECASE)

SUPABASE_DIRECT_HOST_IPV4_HINT = (
    "Couldn't reach the Supabase direct host (db.<ref>.supabase.co). It's IPv6-only unless you "
    "enable Supabase's IPv4 add-on (Project settings → Add-ons), which is required for change "
    "data capture. For standard (non-CDC) syncs, use the Session pooler host instead "
    "(aws-0-<region>.pooler.supabase.com) with username postgres.<project-ref>."
)

# Port 5432 is the Session pooler. Port 6543 is the Transaction pooler, which does not
# support the transactions and DDL that a destination writer runs.
SUPABASE_DIRECT_HOST_DESTINATION_HINT = (
    "The Supabase direct host (db.<ref>.supabase.co) only accepts IPv6 connections, and PostHog "
    "connects over IPv4. Use the Session pooler host instead (aws-0-<region>.pooler.supabase.com) "
    "with port 5432 and username postgres.<project-ref>. Do not use the Transaction pooler on "
    "port 6543."
)

IPV6_ONLY_HOST_MESSAGE = (
    "This host only accepts IPv6 connections, and PostHog connects over IPv4. Use a host that has an IPv4 address."
)


def ipv6_only_host_message(host: str) -> str:
    if SUPABASE_DIRECT_HOST_RE.match(host.strip()):
        return SUPABASE_DIRECT_HOST_DESTINATION_HINT
    return IPV6_ONLY_HOST_MESSAGE
