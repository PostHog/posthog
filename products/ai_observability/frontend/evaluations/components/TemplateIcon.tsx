import {
    IconBug,
    IconChatHelp,
    IconCheckCircle,
    IconClock,
    IconCode,
    IconEmoji,
    IconEye,
    IconLock,
    IconPiggyBank,
    IconSearch,
    IconShield,
    IconStar,
    IconThumbsDown,
    IconTarget,
    IconThumbsUp,
    IconWarning,
    IconWrench,
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
        default: {
            const exhaustiveCheck: never = icon
            return exhaustiveCheck
        }
    }
}

export function TemplateIcon({ template }: { template: EvaluationTemplate }): JSX.Element {
    return (
        <div className="flex items-center justify-center size-10 shrink-0 rounded-lg bg-primary-3000/10 text-primary-3000">
            <TemplateIconGlyph icon={template.icon} />
        </div>
    )
}
