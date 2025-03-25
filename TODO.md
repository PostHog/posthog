Objective: Migrate the startup program and YC onboarding forms from posthog.com into posthog (this repo), while simplifying them by pre-filling information based on available data.

Resources:
- Startup program page in posthog.com: https://github.com/PostHog/posthog.com/blob/1ee825ee2dd67c00082a24755c3b9d61657a1cd1/src/pages/startups/apply.tsx
- YC onboarding page in posthog.com: https://github.com/PostHog/posthog.com/blob/1ee825ee2dd67c00082a24755c3b9d61657a1cd1/src/pages/yc-onboarding.tsx
- SalesforceForm in posthog.com (used on both pages above): https://github.com/PostHog/posthog.com/blob/1ee825ee2dd67c00082a24755c3b9d61657a1cd1/src/components/SalesforceForm/index.tsx

Requirements:
- Both regular startup program and YC variant should share the same logic
- The regular startup program should use /startups URL and YC variant should use /startups/yc URL
- Use best practices on implementing logic and forms (https://keajs.org/docs/plugins/forms/) using Kea (v3)

Steps:
- [x] Implement a startupProgramLogic in frontend using Kea, which should be able to handle both regular and YC applications
  - [x] Connect it to other relevant logics, e.g. 
    - [x] featureFlagLogic (we'll want to manage who can access these pages using feature flags)
    - [x] billingLogic (we'll need to know if they're already on a paid plan, if they're already in a startup program)
    - [x] organizationLogic (we'll want to check organization name, if they're an owner or admin to determine access to these pages)
    - [x] userLogic (we'll want to check their name, email)
  - [x] Implement forms in logic with relevant fields (see below)
    - [x] Define default values for each field
    - [x] Validate fields on touch and submission (required, enums) and show errors accordingly
    - [x] On submission console.log the submitted values
- [x] Implement a startupProgramScence in frontend
  - [x] Basic form using Kea form component and fields described below using components from lemon-ui
- [x] Implement a check on whether their already on a paid plan
  - [x] Use billingLogic to determine
  - [x] If not on a paid plan, show CTA to upgrade (link to /organization/billing)
  - [x] Prevent submit if not on paid plan
- [ ] Implement form validation and error handling
  - [ ] Add validation for required fields, email format, domain format
  - [ ] Add non-YC validation (company age < 2 years, funding < $5M) and show that they're not eligible upon submission attempt
- [ ] Implement form submission
  - [ ] Add loading states and success/error handling
  - [ ] Trigger webhook upon submission
- [ ] Implement access control
  - [ ] Connect to feature flags for page access
  - [ ] Add loading states while checking permissions

---

# Startup Application Form Fields

* type - hidden, prefilled to "contact" (relevant for Zapier webhook that adds contact to Salesforce)

* source - hidden, prefilled based on URL (relevant for Zapier webhook that adds contact to Salesforce, and for the YC batch field)
  * Label: n/a (hidden field)
  * Type: enumeration
  * Required: No
  * Options:
    * YC - if URL is /startups/yc
    * startup - otherwise

* email - prefilled from userLogic
  * Label: Email
  * Type: string (email)
  * Required: Yes

* first_name - prefilled from userLogic
  * Label: First name
  * Type: string
  * Required: Yes

* last_name - prefilled from userLogic
  * Label: Last name
  * Type: string
  * Required: Yes

* startup_domain - prefilled based on email (via userLogic), unless it's a well-known public email domain, then blank
  * Label: Company domain
  * Type: string
  * Required: Yes

* posthog_organization_name - prefilled based on organizationLogic
  * Label: PostHog organization name
  * Type: string
  * Required: Yes

* raised - not prefilled
  * Label: How much in total funding have you raised (USD)
  * Type: enumeration
  * Required: Yes
  * Options:
    * Bootstrapped (0)
    * Under $100k (100000)
    * $100k - $500k (500000)
    * $500k - $1m (1000000)
    * $1m - $5m (5000000)
    * More than $5m (100000000000)

* incorporation_date - not prefilled
  * Label: The date that your company was incorporated
  * Type: string (date)
  * Required: Yes

* is_building_with_llms - not prefilled
  * Label: Are you building LLM-powered features?
  * Type: enumeration
  * Required: Yes
  * Options:
    * Yes (true)
    * No (false)

---

# YC Onboarding Form Fields - same as above with an additional question

* yc_batch - not prefilled
  * Label: Which YC batch are you?
  * Type: enumeration
  * Required: Yes (if source field is "YC")
  * Options:
    * Select your batch (empty)
    * Summer 2025 (S25)
    * Spring 2025 (X25)
    * Winter 2025 (W25)
    * Fall 2024 (F24)
    * Summer 2024 (S24)
    * Winter 2024 (W24)
    * Summer 2023 (S23)
    * Winter 2023 (W23)
    * Summer 2022 (S22)
    * Winter 2022 (W22)
    * Summer 2021 (S21)
    * Winter 2021 (W21)
    * Earlier batches (Earlier)