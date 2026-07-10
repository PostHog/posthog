import {
    IconAI,
    IconChat,
    IconCheckCircle,
    IconCode,
    IconFlag,
    IconFlask,
    IconGraph,
    IconGroups,
    IconImage,
    IconList,
    IconMapPin,
    IconPeople,
    IconPerson,
    IconPieChart,
    IconPython,
    IconRewindPlay,
    IconRocket,
    IconSquareRoot,
    IconUserPaths,
    IconWarning,
} from '@posthog/icons'

import { IconBracketsChart } from 'lib/lemon-ui/icons'

import { NotebookNodeType } from './types'

// Single source of truth for icons that represent a notebook node type.
// Consumers (preview, slash menu, etc.) read from here; missing entries fall
// back to the generic notebook icon at the consumer site.
export const NODE_ICONS: Partial<Record<NotebookNodeType, JSX.Element>> = {
    [NotebookNodeType.Query]: <IconGraph />,
    [NotebookNodeType.HogQLSQL]: <IconBracketsChart />,
    [NotebookNodeType.DuckSQL]: <IconBracketsChart />,
    [NotebookNodeType.SQLV2]: <IconBracketsChart />,
    [NotebookNodeType.Python]: <IconPython />,
    [NotebookNodeType.PythonV2]: <IconPython />,
    [NotebookNodeType.InputV2]: <IconCode />,
    [NotebookNodeType.Latex]: <IconSquareRoot />,
    [NotebookNodeType.Recording]: <IconRewindPlay />,
    [NotebookNodeType.RecordingPlaylist]: <IconRewindPlay />,
    [NotebookNodeType.Image]: <IconImage />,
    [NotebookNodeType.Experiment]: <IconFlask />,
    [NotebookNodeType.Survey]: <IconChat />,
    [NotebookNodeType.Cohort]: <IconPeople />,
    [NotebookNodeType.Embed]: <IconCode />,
    [NotebookNodeType.EarlyAccessFeature]: <IconRocket />,
    [NotebookNodeType.FeatureFlag]: <IconFlag />,
    [NotebookNodeType.FeatureFlagCodeExample]: <IconCode />,
    [NotebookNodeType.Group]: <IconGroups />,
    [NotebookNodeType.GroupProperties]: <IconList />,
    [NotebookNodeType.Issues]: <IconWarning />,
    [NotebookNodeType.LLMTrace]: <IconAI />,
    [NotebookNodeType.Map]: <IconMapPin />,
    [NotebookNodeType.RelatedGroups]: <IconGroups />,
    [NotebookNodeType.Person]: <IconPerson />,
    [NotebookNodeType.PersonProperties]: <IconPerson />,
    [NotebookNodeType.PersonFeed]: <IconPerson />,
    [NotebookNodeType.SupportTickets]: <IconChat />,
    [NotebookNodeType.UsageMetrics]: <IconPieChart />,
    [NotebookNodeType.ZendeskTickets]: <IconChat />,
    [NotebookNodeType.TaskCreate]: <IconCheckCircle />,
    [NotebookNodeType.CustomerJourney]: <IconUserPaths />,
}
