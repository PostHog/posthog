# Marketing analytics page visibility

The `new-marketing-analytics-dashboard` preview includes Page visibility between Ad performance and Setup.
Open `/marketing?tab=page-visibility` within the current project.

Page visibility reuses Web Analytics Page performance: page metrics, Google search visibility, AI referrals, crawler activity, and conversion breakdowns.
Its date, domain, device, comparison, path cleaning, conversion goal, and property controls retain the existing query definitions.
Filter changes keep the Marketing analytics route, and shared URLs restore those filters.
No project-specific conversion goal or campaign is preselected.

Google search and crawler sections retain the existing setup requirements and empty states.
The original Web Analytics Page performance tab keeps its existing feature flag and URL.

Marketing-specific AI tools and attached context are inactive on Page visibility because its controls use independent Web Analytics state.

Page visibility keeps its filters, dates, comparison and conversion goal separate from Web Analytics, including across reloads. Each surface restores only its own URLs.
