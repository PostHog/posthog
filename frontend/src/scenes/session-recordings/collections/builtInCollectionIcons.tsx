import { IconClock, IconComment, IconDownload, IconRewindPlay, IconShare, IconWarning } from '@posthog/icons'

export const BUILT_IN_COLLECTION_ICONS: Record<string, JSX.Element> = {
    'synthetic-watch-history': <IconRewindPlay />,
    'synthetic-commented': <IconComment />,
    'synthetic-shared': <IconShare />,
    'synthetic-exported': <IconDownload />,
    'synthetic-expiring': <IconClock />,
    'synthetic-frustrated': <IconWarning />,
}
