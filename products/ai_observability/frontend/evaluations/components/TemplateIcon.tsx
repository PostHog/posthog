import {
    IconBrackets,
    IconBug,
    IconChatHelp,
    IconCheckCircle,
    IconClock,
    IconCode,
    IconEmoji,
    IconEye,
    IconFlag,
    IconLock,
    IconPiggyBank,
    IconRefresh,
    IconSearch,
    IconShield,
    IconStar,
    IconThumbsDown,
    IconTarget,
    IconThumbsUp,
    IconUndo,
    IconWarning,
    IconWrench,
    IconXCircle,
} from '@posthog/icons'

import type { EvaluationTemplate } from '../templates'

const ICON_CLASS = 'size-5 shrink-0'

function TemplateIconGlyph({ icon }: { icon: EvaluationTemplate['icon'] }): JSX.Element {
    switch (icon) {
        case 'target':
            return <IconTarget className={ICON_CLASS} />
        case 'thumbs-up':
            return <IconThumbsUp className={ICON_CLASS} />
        case 'eye':
            return <IconEye className={ICON_CLASS} />
        case 'alert-triangle':
            return <IconWarning className={ICON_CLASS} />
        case 'code':
            return <IconCode className={ICON_CLASS} />
        case 'search':
            return <IconSearch className={ICON_CLASS} />
        case 'wrench':
            return <IconWrench className={ICON_CLASS} />
        case 'emoji':
            return <IconEmoji className={ICON_CLASS} />
        case 'star':
            return <IconStar className={ICON_CLASS} />
        case 'bug':
            return <IconBug className={ICON_CLASS} />
        case 'check-circle':
            return <IconCheckCircle className={ICON_CLASS} />
        case 'chat':
            return <IconChatHelp className={ICON_CLASS} />
        case 'shield':
            return <IconShield className={ICON_CLASS} />
        case 'lock':
            return <IconLock className={ICON_CLASS} />
        case 'thumbs-down':
            return <IconThumbsDown className={ICON_CLASS} />
        case 'piggy-bank':
            return <IconPiggyBank className={ICON_CLASS} />
        case 'clock':
            return <IconClock className={ICON_CLASS} />
        case 'x-circle':
            return <IconXCircle className={ICON_CLASS} />
        case 'refresh':
            return <IconRefresh className={ICON_CLASS} />
        case 'flag':
            return <IconFlag className={ICON_CLASS} />
        case 'undo':
            return <IconUndo className={ICON_CLASS} />
        case 'brackets':
            return <IconBrackets className={ICON_CLASS} />
        default: {
            const exhaustiveCheck: never = icon
            return exhaustiveCheck
        }
    }
}

// Tailwind's blue, green and purple scales are single colors in this repo, so the tints use sky, emerald and violet.
const CATEGORY_TONES: Record<EvaluationTemplate['category'], string> = {
    quality: 'bg-sky-500/10 text-sky-600',
    safety: 'bg-red-500/10 text-red-500',
    agents: 'bg-violet-500/10 text-violet-500',
    users: 'bg-emerald-500/10 text-emerald-600',
    cost_speed: 'bg-orange-500/10 text-orange-500',
}

export function TemplateIcon({ template }: { template: EvaluationTemplate }): JSX.Element {
    return (
        <div
            className={`flex items-center justify-center size-10 shrink-0 rounded-lg ${CATEGORY_TONES[template.category]}`}
        >
            <TemplateIconGlyph icon={template.icon} />
        </div>
    )
}
