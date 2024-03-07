import * as packageIcons from '@posthog/icons'
import { Meta } from '@storybook/react'

import { LemonCollapse } from '../LemonCollapse'

const meta: Meta = {
    title: 'PostHog 3000/Icons',
    tags: ['autodocs'],
}
export default meta

const posthogIcons = Object.entries(packageIcons)
    .filter(([key]) => key !== 'IconBase')
    .map(([key, Icon]) => ({ name: key, icon: Icon }))

const CATEGORIES = {
    Arrows: [
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
    ],
    Logos: ['IconLogomark', 'IconGithub', 'IconHogQL'],
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
    'Feature Success': ['IconFlask', 'IconTestTube', 'IconMultivariateTest', 'IconSplitTesting'],
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
    'Messaging & Communication': [
        'IconSend',
        'IconHeadset',
        'IconMessage',
        'IconNotification',
        'IconLetter',
        'IconNewspaper',
        'IconChat',
        'IconThoughtBubble',
    ],
    Devices: [
        'IconLaptop',
        'IconPhone',
        'IconWebcam',
        'IconMicrophone',
        'IconKeyboard',
        'IconServer',
        'IconDatabase',
        'IconHardDrive',
    ],
    Objects: [
        'IconPalette',
        'IconCloud',
        'IconCart',
        'IconMegaphone',
        'IconRocket',
        'IconMap',
        'IconClock',
        'IconTie',
        'IconClock',
        'IconCoffee',
        'IconPiggyBank',
        'IconFlag',
        'IconCreditCard',
        'IconHourglass',
        'IconCalendar',
        'IconCrown',
        'IconBolt',
        'IconBook',
        'IconStore',
        'IconConfetti',
        'IconPresent',
        'IconMagicWand',
        'IconMagic',
        'IconHelmet',
        'IconSpotlight',
    ],
    UI: [
        'IconPassword',
        'IconToggle',
        'IconLoading',
        'IconSpinner',
        'IconBrightness',
        'IconCursor',
        'IconCursorBox',
        'IconCursorClick',
        'IconToolbar',
        'IconToolbarFilled',
    ],
}

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

export function AlphabeticalIcons(): JSX.Element {
    return <IconTemplate icons={posthogIcons} />
}

export function CategoricalIcons(): JSX.Element {
    return (
        <LemonCollapse
            multiple
            panels={[
                ...Object.entries(CATEGORIES).map(([key, icons]) => {
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
                }),
            ]}
        />
    )
}
