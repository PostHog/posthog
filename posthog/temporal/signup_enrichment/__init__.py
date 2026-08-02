# Deliberately no imports here: posthog/api/signup.py imports trigger.py on Django's URLconf
# boot path, and importing any submodule of this package first runs this file. Keeping it empty
# stops that boot path from pulling in workflow.py's products.growth/ee enrichment provider
# chain, which only the Temporal worker needs — see registry.py, imported from
# start_temporal_worker.py, for the WORKFLOWS/ACTIVITIES the worker registers.
