import os
import requests
import slack
from slack import WebClient

def post_to_slack():

	headers = {'Content-type':'application/json'}
	payload = {"text":"Aaron, you're a wonderful man."}
	r = requests.post("https://hooks.slack.com/services/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", json=payload, headers=headers)


