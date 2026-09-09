import React from 'react'
import {
    Activity as ActivityIcon,
    Bell as BellIcon,
    ChevronsUpDown as ChevronsUpDownIcon,
    Filter as FilterIcon,
    Folder as FolderIcon,
    House as HouseIcon,
    Inbox as InboxIcon,
    Plus as PlusIcon,
    Repeat as RepeatIcon,
    Search as SearchIcon,
    Settings as SettingsIcon,
    Shapes as ShapesIcon,
} from 'lucide-react'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    MenuLabel,
    Separator,
    Text,
} from '../../../packages/primitives/src'
import type { Meta, StoryObj } from '@storybook/react'

const meta = {
    title: 'Examples/Layout',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

const Nav = (): React.ReactElement => (
    <nav className="flex flex-col gap-2 p-2 rounded-lg w-[200px]">
        <ul className="bg-muted p-4 flex flex-col gap-px [&>li]:w-full [&_button]:w-full rounded-lg">
            <li><MenuLabel>Menu Label</MenuLabel></li>
            <li className="mb-1"><Button left variant="primary">Primary</Button></li>
            <li><Button left aria-expanded>Expanded</Button></li>
            <li><Button left aria-selected>Selected</Button></li>
            <li><Button left>Default</Button></li>
        </ul>
        <ul className="p-4 flex flex-col gap-px [&>li]:w-full [&_button]:w-full rounded-lg">
            <li><MenuLabel>Menu Label</MenuLabel></li>
            <li><Button left variant="primary">Primary</Button></li>
            <li><Button left aria-expanded>Expanded</Button></li>
            <li><Button left aria-selected>Selected</Button></li>
            <li><Button left>Default</Button></li>
        </ul>
    </nav>
)

const Main = (): React.ReactElement => (
    <main className="flex flex-col gap-4 flex-1 rounded-lg p-4">
        <h1 className="text-xl font-bold">Main content</h1>
        <Card size="sm">
            <CardHeader>
                <CardTitle>Card Title</CardTitle>
            </CardHeader>
            <CardContent>
                <p>Card Content</p>
            </CardContent>
            <CardFooter>
                <Button>Action</Button>
            </CardFooter>
        </Card>
    </main>
)

const Aside = (): React.ReactElement => (
    <aside className="p-2 rounded-lg w-[200px] [--theme-hue:570] [--theme-dark-hue:189]">
        <ul className="flex flex-col gap-px [&>li]:w-full [&_button]:w-full bg-muted p-4 rounded-lg">
            <li><MenuLabel>Menu Label</MenuLabel></li>
            <li><Button left variant="primary">Primary</Button></li>
            <li><Button left aria-expanded>Expanded</Button></li>
            <li><Button left aria-selected>Selected</Button></li>
            <li><Button left>Default</Button></li>
        </ul>
    </aside>
)

export const Default: Story = {
    render: () => (
        <div className="flex rounded-lg bg-background gap-4">
            <Nav />
            <Main />
            <Aside />
        </div>
    ),
} satisfies Story


const RAIL_DESTINATIONS: { label: string; Icon: typeof HouseIcon; current?: boolean }[] = [
    { label: 'Home', Icon: HouseIcon, current: true },
    { label: 'Inbox', Icon: InboxIcon },
    { label: 'Activity', Icon: ActivityIcon },
    { label: 'Loops', Icon: RepeatIcon },
    { label: 'Spaces', Icon: ShapesIcon },
]

const NavRail = (): React.ReactElement => (
    <nav
        aria-label="Destinations"
        className="flex w-11 shrink-0 flex-col items-center gap-1 border-border border-r py-2"
    >
        <Button size="icon" aria-label="Search">
            <SearchIcon />
        </Button>
        <Separator className="my-1 w-6" />
        {RAIL_DESTINATIONS.map(({ label, Icon, current }) => (
            <Button
                key={label}
                size="icon"
                aria-label={label}
                aria-current={current ? 'page' : undefined}
                className={current ? 'bg-fill-selected' : undefined}
            >
                <Icon />
            </Button>
        ))}
        <div className="mt-auto flex flex-col items-center gap-1">
            <Button size="icon" aria-label="Notifications">
                <BellIcon />
            </Button>
            <Button size="icon" aria-label="Settings">
                <SettingsIcon />
            </Button>
        </div>
    </nav>
)

const Sidebar = (): React.ReactElement => (
    <aside className="flex w-[272px] shrink-0 flex-col gap-2 border-border border-r p-2">
        <div className="flex items-center gap-1">
            <Button left className="min-w-0 flex-1">
                <FolderIcon />
                <span className="truncate">posthog / code</span>
                <ChevronsUpDownIcon className="ml-auto" />
            </Button>
            <Button size="icon" aria-label="New task">
                <PlusIcon />
            </Button>
        </div>
        <div className="flex flex-col gap-px [&_button]:w-full">
            <MenuLabel>Pinned</MenuLabel>
            <Button left>Rebuild the nav rail</Button>
            <Button left>Ship the layout story</Button>
        </div>
        <div className="flex flex-col gap-px [&_button]:w-full">
            <MenuLabel>Channels</MenuLabel>
            <Button left>#general</Button>
            <Button left>#design-system</Button>
            <Button left aria-current="page" className="bg-fill-selected">
                #desktop
            </Button>
            <Button left>#releases</Button>
        </div>
    </aside>
)

const TopBar = (): React.ReactElement => (
    <header className="flex h-10 shrink-0 items-center gap-2 border-border border-b px-3">
        <Text size="sm" weight="semibold" render={<span />} className="truncate">
            #desktop
        </Text>
        <Badge>4 members</Badge>
        <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="icon-sm" aria-label="Filter">
                <FilterIcon />
            </Button>
            <Button variant="outline" size="sm">
                Share
            </Button>
            <Button variant="primary" size="sm">
                New task
            </Button>
        </div>
    </header>
)

export const BasicLayout: Story = {
    parameters: { layout: 'fullscreen' },
    render: () => (
        <div className="flex h-[640px] overflow-hidden bg-muted border border-border rounded-lg">
            <NavRail />
            <Sidebar />
            <main className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-tl-sm bg-background">
                <TopBar />
                <div className="flex-1 overflow-auto" />
            </main>
        </div>
    ),
} satisfies Story
