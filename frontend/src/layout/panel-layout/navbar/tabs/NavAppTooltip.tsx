import { FileSystemImport } from '~/queries/schema/schema-general'

import { sidebarToolMeta } from '../../sidebarToolMeta'
import { appsItemName } from './appsCatalog'

const descriptions: Record<string, string> = {
    Home: 'Pick up where you left off with the insights, dashboards, and activity that matter to your project.',
    Activity:
        'Explore the events people send to your project. Inspect their properties to understand exactly what happened.',
    'SQL editor':
        'Ask questions that need more than a chart builder. Query your events and warehouse tables together, then turn the results into a table or visualization.',
    'Product analytics':
        'Find out how people discover, use, and return to your product. Explore trends, conversion funnels, retention, and the paths people take.',
    Dashboards:
        'Bring related insights together in one place. Follow your key metrics over time and share the same view of progress with your team.',
    'Session replay':
        'Watch how people actually experience your product. Follow their clicks and navigation to understand the behavior behind a metric or bug report.',
    'Feature flags':
        'Choose who sees a feature without another deployment. Roll changes out gradually, target a specific group, or turn a feature off when something goes wrong.',
    Experiments:
        'Compare product changes with a controlled test. Measure their effect on the metrics you care about before deciding what to ship.',
    'Web analytics':
        'Understand who visits your website, where they come from, and which pages lead to conversions. Start with traffic, then explore what drives it.',
    'Error tracking':
        'Turn exceptions into issues you can investigate. See who was affected and connect errors with the context you need to find the cause.',
    Surveys:
        'Ask people about their experience while it is still fresh. Collect feedback in your product and use it to explain what your analytics cannot.',
    Heatmaps:
        'See where people click and how far they scroll. Spot overlooked calls to action and places where a page loses attention.',
    Notebooks:
        'Keep an investigation together with notes, insights, and recordings. Give your team the evidence and context behind your conclusions.',
    'LLM analytics':
        'Follow your AI application from prompts to responses. Inspect traces, latency, token usage, and cost to understand quality and performance.',
    Persons:
        'Explore the people behind your events, including their properties and activity. Connect an individual experience with the patterns in your analytics.',
    Cohorts:
        'Group people by what they do and who they are. Reuse those audiences in analysis, feature targeting, and experiments.',
    'SQL variables':
        'Define reusable values for SQL queries so you can change a shared parameter without editing every query.',
    'Core events':
        'Choose the events that signal meaningful use of your product. Give your team a shared starting point for understanding customer activity.',
    'Revenue definitions':
        'Tell PostHog which events represent revenue and where to find their amounts and currencies. Use consistent revenue measures across your analyses.',
    'Property groups':
        'Organize related properties into reusable groups. Make a large tracking schema easier to navigate and understand.',
    'Event definitions':
        'Explore the events captured in your project and document what they mean. Help your team choose the right events for an analysis.',
    'Property definitions':
        'Explore the properties attached to your events and people. Document their meaning so everyone interprets the same data consistently.',
    'Managed viewsets':
        'Set up collections of warehouse views built for a particular kind of analysis. Reuse prepared data models instead of starting each query from scratch.',
    'Event ingestion warnings':
        'Find problems encountered while processing your events. Inspect the warnings to identify tracking issues and improve the data you analyze.',
    Annotations:
        'Add context to changes in your metrics. Mark releases, campaigns, and other milestones so your team can connect a chart with what happened.',
    Sources:
        'Bring data from your other tools into PostHog. Combine it with product events to answer questions that span your business.',
    Destinations:
        'Send events from PostHog to the tools that need them. Connect product activity with the rest of your workflows.',
    Transformations:
        'Reshape incoming events before they reach your analyses. Keep event names and properties consistent across your tracking.',
    Models: 'Turn SQL queries into reusable views and materialized views. Build on shared data models instead of repeating the same preparation in every analysis.',
}

const examples: Record<string, string> = {
    Home: 'Return to a dashboard you were investigating yesterday.',
    Activity: 'Check which properties arrive with a signup event.',
    'SQL editor': 'Join signup events with billing data to compare activation by plan.',
    'Product analytics': 'Find the step where new users drop out of onboarding.',
    Dashboards: 'Keep activation, retention, and revenue on a weekly team dashboard.',
    'Session replay': 'Watch a failed checkout to see what got in the way.',
    'Feature flags': 'Try a new navigation with your team before rolling it out to everyone.',
    Experiments: 'Test whether a shorter signup flow improves activation.',
    'Web analytics': 'Find which referral sources bring visitors who sign up.',
    'Error tracking': 'Investigate an exception that appeared after a release.',
    Surveys: 'Ask people who abandon a flow what they were trying to do.',
    Heatmaps: 'Check whether visitors reach your pricing call to action.',
    Notebooks: 'Share a funnel drop-off alongside recordings that explain it.',
    'LLM analytics': 'Find the model calls making an assistant slow or expensive.',
    Persons: 'Review a user’s recent events while investigating a support question.',
    Cohorts: 'Compare people who tried a feature with those who have not.',
    'AI gateway': 'Compare model usage across projects through a shared API.',
    Apps: 'Build an internal Python dashboard using your project data.',
    Broadcasts: 'Send an announcement to a cohort of beta testers.',
    'Business knowledge': 'Give your AI assistant context about how your business works.',
    Clusters: 'Discover common themes in conversations with your AI assistant.',
    'Code review': 'Review automated findings on a pull request before it merges.',
    'Customer analytics': 'Explore activity across the accounts that use your product.',
    'Data catalog': 'Find the agreed definition of a metric before using it.',
    'Data warehouse': 'Manage the shared data your team uses for analysis.',
    Datasets: 'Keep representative prompts and expected answers for testing.',
    'Early access features': 'Let interested users opt into a public beta.',
    Endpoints: 'Serve a saved query to your application and track its usage.',
    'Engineering analytics': 'Find workflows that slow down pull requests.',
    Evaluations: 'Check whether AI responses meet your quality criteria.',
    'Identity matching': 'Review how identities connect across your data.',
    Inbox: 'Review a report about friction discovered in user sessions.',
    Links: 'Create a trackable link for a new campaign.',
    'Live Debugger': 'Inspect the state of running code when a breakpoint fires.',
    Logs: 'Search application logs around the time an error occurred.',
    'MCP analytics': 'See which tools AI users call and what they are trying to achieve.',
    'MCP servers': 'Find a server that gives your agent the tools it needs.',
    'Marketing analytics': 'Compare campaign performance alongside your product data.',
    Metrics: 'Investigate a change in application performance over time.',
    Playground: 'Try a revised prompt before using it in your application.',
    'Product tours': 'Guide new users through their first useful action.',
    Prompts: 'Keep track of changes to the prompts your application uses.',
    Pulse: 'Follow what is happening across your project.',
    'Replay vision': 'Explore patterns found in session recordings.',
    Skills: 'Share reusable instructions with the agents your team uses.',
    Support: 'Investigate and respond to a customer’s support request.',
    Taggers: 'Label AI generations so you can compare different kinds of requests.',
    Tasks: 'Ask an agent to investigate an issue and prepare a code change.',
    Toolbar: 'Inspect elements on your website while setting up tracking.',
    Tracing: 'Follow a slow request across services to find the bottleneck.',
    'User research': 'Run a voice research campaign about a recent product experience.',
    'Visual review': 'Review visual changes before they reach users.',
    'Web scripts': 'Add a website tag without changing your application code.',
    Wizard: 'Review the code changes an agent prepares to set up PostHog.',
    Workflows: 'Send a follow-up when someone completes an onboarding step.',
    Actions: 'Combine related clicks into a single event for analysis.',
    Annotations: 'Mark a release date to help explain a change in a chart.',
    'Core events': 'Define the events that represent meaningful product usage.',
    Destinations: 'Send captured events to another tool your team uses.',
    'Event definitions': 'Check what an event means before adding it to an insight.',
    'Event ingestion filtering': 'Filter unwanted events before they enter your project.',
    'Event ingestion warnings': 'Investigate events that were not ingested as expected.',
    'Managed migrations': 'Bring historical events into PostHog.',
    'Managed viewsets': 'Set up a collection of warehouse views for analysis.',
    Models: 'Save a reusable query as a view for other analyses.',
    'Property definitions': 'Check the meaning and format of an event property.',
    'Property groups': 'Organize related properties so they are easier to find.',
    'Revenue definitions': 'Choose the events and properties that represent revenue.',
    'SQL variables': 'Reuse the same date boundary across several queries.',
    Sources: 'Connect billing or support data to your product analytics.',
    Transformations: 'Clean or reshape incoming data before you analyze it.',
    'Warehouse destinations': 'Choose where a warehouse source sends its synced rows.',
    'Warehouse properties': 'Add account attributes from a warehouse table to your groups.',
}

export function NavAppTooltip({ item }: { item: FileSystemImport }): JSX.Element {
    const description = descriptions[item.path] ?? sidebarToolMeta(item).description
    const example = examples[item.path]
    const isGroup = item.iconType === 'group' || item.iconType?.startsWith('group_') || item.type?.startsWith('group_')
    return (
        <div className="w-72 max-w-full p-1 text-left whitespace-normal">
            <div className="text-sm font-semibold mb-2">{appsItemName(item)}</div>
            <div className="text-xs leading-relaxed">
                {description ??
                    (isGroup
                        ? 'Explore the organizations, accounts, or other groups behind your events. Understand usage at the group level.'
                        : `Explore ${appsItemName(item).toLowerCase()} in your project.`)}
            </div>
            {(example || isGroup) && (
                <div className="mt-3 border-t border-current/20 pt-2">
                    <div className="text-xs font-semibold mb-1">For example</div>
                    <div className="text-xs leading-relaxed text-secondary">
                        {example ?? 'Compare activity across customer accounts.'}
                    </div>
                </div>
            )}
        </div>
    )
}
