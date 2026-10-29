import {
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
} from '@posthog/icons'

import type { EvaluationTemplate } from '../templates'

// Typed as a Record so adding an icon name without a component fails the type check.
const ICONS: Record<EvaluationTemplate['icon'], React.ComponentType<{ className?: string }>> = {
    target: IconTarget,
    'thumbs-up': IconThumbsUp,
    eye: IconEye,
    'alert-triangle': IconWarning,
    code: IconCode,
    search: IconSearch,
    wrench: IconWrench,
    emoji: IconEmoji,
    star: IconStar,
    bug: IconBug,
    'check-circle': IconCheckCircle,
    chat: IconChatHelp,
    shield: IconShield,
    lock: IconLock,
    'thumbs-down': IconThumbsDown,
    'piggy-bank': IconPiggyBank,
    clock: IconClock,
    refresh: IconRefresh,
    flag: IconFlag,
    undo: IconUndo,
}

const CATEGORY_TONES: Record<EvaluationTemplate['category'], string> = {
    quality: 'bg-sky-500/10 text-sky-600',
    safety: 'bg-red-500/10 text-red-500',
    agents: 'bg-violet-500/10 text-violet-500',
    users: 'bg-emerald-500/10 text-emerald-600',
    cost_speed: 'bg-orange-500/10 text-orange-500',
}

export function TemplateIcon({ template }: { template: EvaluationTemplate }): JSX.Element {
    const Glyph = ICONS[template.icon]
    return (
        <div
            className={`flex items-center justify-center size-10 shrink-0 rounded-lg ${CATEGORY_TONES[template.category]}`}
        >
            <Glyph className="size-5 shrink-0" />
        </div>
    )
}
