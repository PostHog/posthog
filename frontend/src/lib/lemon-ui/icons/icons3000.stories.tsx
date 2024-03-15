import * as packageIcons from '@posthog/icons'
import { Meta, StoryObj } from '@storybook/react'

import { LemonCollapse } from '../LemonCollapse'

const meta: Meta = {
    title: 'PostHog 3000/Icons',
    tags: ['test-skip'],
    parameters: {
        previewTabs: {
            'storybook/docs/panel': {
                hidden: true,
            },
        },
    },
}
export default meta

const posthogIcons = Object.entries(packageIcons)
    .filter(([key]) => key !== 'BaseIcon')
    .map(([key, Icon]) => ({ name: key, icon: Icon }))

export const UNUSED_ICONS = [
    'IconAdvanced',
    'IconAstreisk',
    'IconGridMasonry',
    'IconApps',
    'IconRibbon',
    'IconPulse',
    'IconPineapple',
    'IconPizza',
    'IconTarget',
    'IconThumbsUp',
    'IconThumbsDown',
]

const OBJECTS = {
    Misc: [
        'IconPalette',
        'IconMegaphone',
        'IconRocket',
        'IconMap',
        'IconTie',
        'IconCoffee',
        'IconFlag',
        'IconCreditCard',
        'IconCrown',
        'IconBolt',
        'IconBook',
        'IconConfetti',
        'IconPresent',
        'IconMagicWand',
        'IconMagic',
        'IconHelmet',
        'IconSpotlight',
        'IconGraduationCap',
        'IconLightBulb',
        'IconBell',
        'IconBox',
        'IconBuilding',
        'IconEye',
        'IconFeatures',
        'IconHome',
        'IconHomeFilled',
        'IconGear',
        'IconGearFilled',
        'IconStack',
    ],
    People: ['IconPeople', 'IconPeopleFilled', 'IconPerson', 'IconProfile', 'IconUser'],
    'Business & Finance': ['IconStore', 'IconCart', 'IconReceipt', 'IconPiggyBank'],
    Time: ['IconHourglass', 'IconCalendar', 'IconClock'],
    Nature: ['IconDay', 'IconNight', 'IconGlobe', 'IconCloud', 'IconBug'],
    Text: ['IconDocument', 'IconBrackets', 'IconTextWidth', 'IconQuote', 'IconLetter', 'IconNewspaper'],
}

const TECHNOLOGY = {
    Messaging: ['IconSend', 'IconHeadset', 'IconMessage', 'IconNotification', 'IconChat', 'IconThoughtBubble'],
    Hardware: [
        'IconLaptop',
        'IconPhone',
        'IconWebcam',
        'IconMicrophone',
        'IconKeyboard',
        'IconServer',
        'IconDatabase',
        'IconHardDrive',
    ],
    Software: ['IconBrowser', 'IconCode', 'IconCodeInsert', 'IconTerminal', 'IconApp'],
    UI: [
        'IconPassword',
        'IconToggle',
        'IconLoading',
        // 'IconSpinner',
        'IconBrightness',
        'IconCursor',
        'IconCursorBox',
        'IconCursorClick',
        'IconToolbar',
        'IconToolbarFilled',
        'IconCheckbox',
        'IconList',
        'IconColumns',
    ],
}

const ELEMENTS = {
    Actions: [
        'IconCopy',
        'IconTrash',
        'IconUndo',
        'IconRedo',
        'IconRevert',
        'IconSearch',
        'IconUpload',
        'IconShare',
        'IconDownload',
        'IconLeave',
        'IconPin',
        'IconPinFilled',
        'IconPencil',
        'IconOpenSidebar',
        'IconFilter',
        'IconArchive',
        'IconSort',
        'IconExternal',
    ],
    Symbols: [
        'IconLock',
        'IconUnlock',
        'IconPrivacy',
        'IconShield',
        'IconWarning',
        'IconQuestion',
        'IconInfo',
        'IconCheckCircle',
        'IconCheck',
        'IconX',
        'IconEllipsis',
    ],
    'Arrows & Shapes': [
        'IconArrowLeft',
        'IconArrowRight',
        'IconArrowCircleLeft',
        'IconArrowCircleRight',
        'IconArrowRightDown',
        'IconArrowUpRight',
        'IconCollapse',
        'IconExpand',
        'IconCollapse45',
        'IconExpand45',
        'IconChevronDown',
        'IconTriangleDown',
        'IconTriangleDownFilled',
        'IconTriangleUp',
        'IconTriangleUpFilled',
        'IconStar',
        'IconStarFilled',
        'IconHeart',
        'IconHeartFilled',
    ],
    Mathematics: [
        'IconPlus',
        'IconPlusSmall',
        'IconPlusSquare',
        'IconMinus',
        'IconMinusSmall',
        'IconMinusSquare',
        'IconMultiply',
        'IconPercentage',
        'IconCalculator',
    ],
}

const TEAMS_AND_COMPANIES = {
    Analytics: [
        'IconCorrelationAnalysis',
        'IconGraph',
        'IconLineGraph',
        'IconRetention',
        'IconFunnels',
        'IconGanttChart',
        'IconTrending',
        'IconTrends',
        'IconLifecycle',
        'IconPieChart',
        'IconUserPaths',
        'IconStickiness',
        'IconPageChart',
        'IconSampling',
        'IconLive',
        'IconBadge',
    ],
    Replay: [
        'IconPlay',
        'IconPlayFilled',
        'IconPlaylist',
        'IconPause',
        'IconPauseFilled',
        'IconRewind',
        'IconRecord',
        'IconRewindPlay',
        'IconVideoCamera',
    ],
    'Feature Success': ['IconFlask', 'IconTestTube', 'IconMultivariateTesting', 'IconSplitTesting'],
    Pipeline: ['IconWebhooks', 'IconDecisionTree'],
    'Product OS': ['IconNotebook', 'IconHogQL', 'IconDashboard', 'IconSupport'],
    Logos: ['IconLogomark', 'IconGithub'],
}

export const CATEGORIES = [OBJECTS, TECHNOLOGY, ELEMENTS, TEAMS_AND_COMPANIES]

const IconTemplate = ({ icons }: { icons: { name: string; icon: any }[] }): JSX.Element => {
    return (
        <div className="grid grid-cols-6 gap-4">
            {icons.map(({ name, icon: Icon }) => {
                return (
                    <div key={name} className="flex flex-col items-center space-y-2">
                        <Icon className="w-10 h-10" />
                        <span className="text-xs">{name}</span>
                    </div>
                )
            })}
        </div>
    )
}

export function Alphabetical(): JSX.Element {
    return <IconTemplate icons={posthogIcons} />
}

const GroupBase = ({ group }: { group: Record<string, string[]> }): JSX.Element => {
    return (
        <LemonCollapse
            multiple
            panels={Object.entries(group).map(([key, icons]) => {
                return {
                    key,
                    header: key,
                    content: (
                        <IconTemplate
                            icons={icons.map((icon) => {
                                return { name: icon, icon: packageIcons[icon] }
                            })}
                        />
                    ),
                }
            })}
        />
    )
}

export const Elements: StoryObj = (): JSX.Element => {
    return <GroupBase group={ELEMENTS} />
}
Elements.storyName = 'Category - Elements'

export const TeamsAndCompanies: StoryObj = (): JSX.Element => {
    return <GroupBase group={TEAMS_AND_COMPANIES} />
}
TeamsAndCompanies.storyName = 'Category - Teams & Companies'

export const Technology: StoryObj = (): JSX.Element => {
    return <GroupBase group={TECHNOLOGY} />
}
Technology.storyName = 'Category - Technology'

export const Objects: StoryObj = (): JSX.Element => {
    return <GroupBase group={OBJECTS} />
}
Objects.storyName = 'Category - Objects'
