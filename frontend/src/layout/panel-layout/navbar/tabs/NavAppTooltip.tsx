import { FileSystemImport } from '~/queries/schema/schema-general'

import { sidebarToolMeta } from '../../sidebarToolMeta'
import { appsItemName } from './appsCatalog'

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
    const { description } = sidebarToolMeta(item)
    const example = examples[item.path]
    const isGroup = item.iconType === 'group' || item.iconType?.startsWith('group_') || item.type?.startsWith('group_')
    return (
        <div className="w-72 max-w-full p-1 text-left whitespace-normal">
            <div className="text-sm font-semibold mb-2">{appsItemName(item)}</div>
            <div className="text-xs leading-relaxed">
                {description ?? `Explore ${appsItemName(item).toLowerCase()} in your project.`}
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
