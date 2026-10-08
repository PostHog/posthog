"""Invented business-knowledge corpus for support-reply evals.

Pure and Django-free so the texts can be asserted in unit tests without a database.
Every document is about Acme Capture, a fictional SDK at docs.example.com.
"""

from __future__ import annotations

from posthog.dataclasses import frozen

from products.conversations.evals.constants import (
    SOURCE_BILLING_INVOICES,
    SOURCE_RECORDING_RETENTION,
    SOURCE_REPLAY_BLANK,
    SOURCE_SDK_INSTALL,
    SOURCE_TEAM_POLICY,
)


@frozen
class CorpusDocument:
    name: str
    text: str
    always_include: bool = False


CORPUS: tuple[CorpusDocument, ...] = (
    CorpusDocument(
        name=SOURCE_SDK_INSTALL,
        text=(
            "Install the Acme Capture JavaScript SDK on any site you own.\n\n"
            "Add this snippet to the <head> of every page on app.example.com:\n"
            "<script>acmeCapture.init({ apiHost: 'https://api.example.com', projectToken: 'YOUR_PROJECT_TOKEN' })</script>\n\n"
            "Replace YOUR_PROJECT_TOKEN with the token from Project settings. After a reload, "
            "the SDK sends a $pageview for that URL. Use the same projectToken in iOS and Android "
            "if you want one project to receive every platform. Do not put the token in a public "
            "GitHub issue; rotate it from Project settings if it leaks.\n\n"
            "If events never arrive, confirm the snippet is on the page that fired, the token "
            "matches the project, and an ad blocker is not stripping api.example.com."
        ),
    ),
    CorpusDocument(
        name=SOURCE_BILLING_INVOICES,
        text=(
            "Download invoices from Organization settings > Billing > Invoices on app.example.com.\n\n"
            "Each invoice is a PDF for one calendar month. The billing email on the organization "
            "receives a copy when the invoice is issued. Changing the billing email does not "
            "resend old invoices; download those from the Invoices list.\n\n"
            "Plan changes take effect at the next renewal. Usage for the current period is billed "
            "on the existing plan. Support agents must not issue refunds or credits. Billing "
            "disputes go to the billing team with the organization id and invoice month."
        ),
    ),
    CorpusDocument(
        name=SOURCE_REPLAY_BLANK,
        text=(
            "A session recording that opens as a blank canvas usually means the recorder never "
            "captured DOM snapshots for that session.\n\n"
            "Check, in order: (1) the recording SDK snippet is on the page, (2) the project has "
            "session replay enabled under Project settings > Replay, (3) the session is not "
            "excluded by a URL-blocklist rule, (4) the customer is not blocking the recorder "
            "domain in an ad blocker. A recording with events but no snapshots will still list "
            "in Replay and open blank.\n\n"
            "If those four checks pass, ask for the session id (32-character hex) and the page "
            "URL. Do not ask for cookies or auth tokens."
        ),
    ),
    CorpusDocument(
        name=SOURCE_RECORDING_RETENTION,
        text=(
            "Acme Capture retains session recordings for 30 days on every paid plan.\n\n"
            "The retention clock starts when the session ends. After 30 days the recording is "
            "deleted and cannot be restored. Free plans retain recordings for 7 days. There is "
            "no per-project override; changing plan does not resurrect recordings already deleted.\n\n"
            "A recording that vanished after 3 days is not explained by this policy. Treat that "
            "as a product defect: collect the session id, the project token last-4, and when the "
            "customer last opened the recording, then escalate to engineering."
        ),
    ),
    CorpusDocument(
        name=SOURCE_TEAM_POLICY,
        always_include=True,
        text=(
            "Support reply policy for Acme Capture.\n\n"
            "Lead with the answer. Cite the knowledge base. Never invent a configuration that "
            "is not in these documents. Never promise a refund, a credit, or a plan exception; "
            "those go to the billing team. Never ask the customer to paste an API key, cookie, "
            "or password into the ticket. One question at a time when something is missing."
        ),
    ),
)
