import type { Meta, StoryObj } from '@storybook/react'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSkeleton,
    LemonSnack,
    LemonSwitch,
    LemonTabs,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'
import {
    Badge,
    Button as QuillButton,
    Checkbox,
    Chip,
    Input,
    Kbd,
    Label,
    Progress,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Skeleton,
    Switch,
    Tabs,
    TabsList,
    TabsTrigger,
    Textarea,
} from '@posthog/quill'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LemonButton } from './LemonButton'

/**
 * Prototypes of the two possible "skin bridge" migration directions:
 *
 * - `SideBySide` (quill-skin.scss): LemonButton restyled to quill's visual
 *   language — ship the new look first, migrate code later.
 * - `ReverseSideBySide` (lemon-skin.scss): quill Button restyled to Lemon's
 *   current look — migrate code invisibly first, flip the look at the end.
 *
 * In both stories the middle column renders the exact same code as its
 * reference column — only the skin wrapper attribute differs.
 */
const meta: Meta = {
    title: 'Lemon UI/Lemon Button Quill Skin',
    parameters: {
        testOptions: {
            // The story intentionally shows always-loading buttons, whose spinners
            // would otherwise time out the snapshot runner's loader wait
            waitForLoadersToDisappear: false,
        },
    },
}
export default meta

function LemonExamples(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 items-start">
            <LemonButton type="primary">Primary</LemonButton>
            <LemonButton type="secondary">Secondary</LemonButton>
            <LemonButton type="tertiary">Tertiary</LemonButton>
            <LemonButton type="primary" icon={<IconPlus />}>
                With icon
            </LemonButton>
            <LemonButton type="secondary" status="danger" icon={<IconTrash />}>
                Danger
            </LemonButton>
            <LemonButton type="tertiary" status="danger">
                Danger tertiary
            </LemonButton>
            <LemonButton type="primary" disabledReason="Disabled for demo purposes">
                Disabled
            </LemonButton>
            <LemonButton type="primary" loading>
                Loading
            </LemonButton>
            <div className="flex gap-2 items-center">
                <LemonButton type="secondary" size="xxsmall">
                    xxsmall
                </LemonButton>
                <LemonButton type="secondary" size="xsmall">
                    xsmall
                </LemonButton>
                <LemonButton type="secondary" size="small">
                    small
                </LemonButton>
                <LemonButton type="secondary">medium</LemonButton>
                <LemonButton type="secondary" size="large">
                    large
                </LemonButton>
            </div>
        </div>
    )
}

function QuillExamples(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 items-start">
            <QuillButton variant="primary">Primary</QuillButton>
            <QuillButton variant="outline">Secondary</QuillButton>
            <QuillButton variant="default">Tertiary</QuillButton>
            <QuillButton variant="primary">
                <IconPlus />
                With icon
            </QuillButton>
            <QuillButton variant="destructive">
                <IconTrash />
                Danger
            </QuillButton>
            <QuillButton variant="destructive">Danger tertiary</QuillButton>
            <QuillButton variant="primary" disabled>
                Disabled
            </QuillButton>
            <QuillButton variant="primary" loading>
                Loading
            </QuillButton>
            {/* Labels name the Lemon size each quill size maps to under the skin */}
            <div className="flex gap-2 items-center">
                <QuillButton variant="outline" size="xs">
                    xxsmall
                </QuillButton>
                <QuillButton variant="outline" size="sm">
                    xsmall
                </QuillButton>
                <QuillButton variant="outline">small</QuillButton>
                <QuillButton variant="outline" size="lg">
                    medium
                </QuillButton>
            </div>
        </div>
    )
}

export const SideBySide: StoryObj = {
    render: () => (
        <div className="grid grid-cols-3 gap-4">
            <div className="border rounded p-4">
                <h4 className="mb-4">LemonButton today</h4>
                <LemonExamples />
            </div>
            <div className="border rounded p-4" data-quill data-quill-skin>
                <h4 className="mb-4">LemonButton + quill skin (same code)</h4>
                <LemonExamples />
            </div>
            <div className="border rounded p-4" data-quill>
                <h4 className="mb-4">Quill Button (target)</h4>
                <QuillExamples />
            </div>
        </div>
    ),
}

export const ReverseSideBySide: StoryObj = {
    render: () => (
        <div className="grid grid-cols-3 gap-4">
            <div className="border rounded p-4" data-quill>
                <h4 className="mb-4">Quill Button today</h4>
                <QuillExamples />
            </div>
            <div className="border rounded p-4" data-quill data-lemon-skin>
                <h4 className="mb-4">Quill Button + lemon skin (same code)</h4>
                <QuillExamples />
            </div>
            <div className="border rounded p-4">
                <h4 className="mb-4">LemonButton (target)</h4>
                <LemonExamples />
            </div>
        </div>
    ),
}

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <h5>{title}</h5>
            {children}
        </div>
    )
}

function QuillKitchenSink({ idPrefix }: { idPrefix: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <Section title="Input">
                <Input placeholder="Type here..." />
            </Section>
            <Section title="Textarea">
                <Textarea placeholder="Longer text here..." />
            </Section>
            <Section title="Checkbox">
                <div className="flex items-center gap-2">
                    <Checkbox id={`${idPrefix}-check`} defaultChecked />
                    <Label htmlFor={`${idPrefix}-check`}>Accept terms</Label>
                </div>
            </Section>
            <Section title="Switch">
                <div className="flex items-center gap-2">
                    <Switch id={`${idPrefix}-switch`} defaultChecked />
                    <Label htmlFor={`${idPrefix}-switch`}>Notifications</Label>
                </div>
            </Section>
            <Section title="Radio">
                <RadioGroup defaultValue="a" className="flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                        <RadioGroupItem value="a" id={`${idPrefix}-radio-a`} />
                        <Label htmlFor={`${idPrefix}-radio-a`}>Option A</Label>
                    </div>
                    <div className="flex items-center gap-2">
                        <RadioGroupItem value="b" id={`${idPrefix}-radio-b`} />
                        <Label htmlFor={`${idPrefix}-radio-b`}>Option B</Label>
                    </div>
                </RadioGroup>
            </Section>
            <Section title="Select (closed)">
                <Select>
                    <SelectTrigger>
                        <SelectValue placeholder="Choose a fruit..." />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="apple">Apple</SelectItem>
                        <SelectItem value="banana">Banana</SelectItem>
                    </SelectContent>
                </Select>
            </Section>
            <Section title="Badge / tag">
                <div className="flex gap-2">
                    <Badge>default</Badge>
                    <Badge variant="success">success</Badge>
                    <Badge variant="warning">warning</Badge>
                    <Badge variant="destructive">danger</Badge>
                </div>
            </Section>
            <Section title="Chip / snack">
                <div className="flex gap-2">
                    <Chip>browser: Chrome</Chip>
                    <Chip>os: macOS</Chip>
                </div>
            </Section>
            <Section title="Kbd">
                <div className="flex gap-1">
                    <Kbd>Cmd</Kbd>
                    <Kbd>K</Kbd>
                </div>
            </Section>
            <Section title="Progress">
                <Progress value={40} />
            </Section>
            <Section title="Skeleton">
                <Skeleton className="h-4 w-32" />
            </Section>
            <Section title="Divider">
                <Separator />
            </Section>
            <Section title="Tabs">
                <Tabs defaultValue="first">
                    <TabsList variant="line">
                        <TabsTrigger value="first">First tab</TabsTrigger>
                        <TabsTrigger value="second">Second tab</TabsTrigger>
                    </TabsList>
                </Tabs>
            </Section>
            <Section title="Label">
                <Label>Field label</Label>
            </Section>
        </div>
    )
}

function LemonKitchenSink(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <Section title="Input">
                <LemonInput placeholder="Type here..." />
            </Section>
            <Section title="Textarea">
                <LemonTextArea placeholder="Longer text here..." />
            </Section>
            <Section title="Checkbox">
                <LemonCheckbox checked label="Accept terms" onChange={() => {}} />
            </Section>
            <Section title="Switch">
                <LemonSwitch checked label="Notifications" onChange={() => {}} />
            </Section>
            <Section title="Radio">
                <LemonRadio
                    value="a"
                    onChange={() => {}}
                    options={[
                        { value: 'a', label: 'Option A' },
                        { value: 'b', label: 'Option B' },
                    ]}
                />
            </Section>
            <Section title="Select (closed)">
                <LemonSelect<string>
                    value={null}
                    onChange={() => {}}
                    placeholder="Choose a fruit..."
                    options={[
                        { value: 'apple', label: 'Apple' },
                        { value: 'banana', label: 'Banana' },
                    ]}
                />
            </Section>
            <Section title="Badge / tag">
                <div className="flex gap-2">
                    <LemonTag>default</LemonTag>
                    <LemonTag type="success">success</LemonTag>
                    <LemonTag type="warning">warning</LemonTag>
                    <LemonTag type="danger">danger</LemonTag>
                </div>
            </Section>
            <Section title="Chip / snack">
                <div className="flex gap-2">
                    <LemonSnack>browser: Chrome</LemonSnack>
                    <LemonSnack>os: macOS</LemonSnack>
                </div>
            </Section>
            <Section title="Kbd">
                <KeyboardShortcut command k />
            </Section>
            <Section title="Progress">
                <LemonProgress percent={40} />
            </Section>
            <Section title="Skeleton">
                <LemonSkeleton className="h-4 w-32" />
            </Section>
            <Section title="Divider">
                <LemonDivider />
            </Section>
            <Section title="Tabs">
                <LemonTabs
                    activeKey="first"
                    onChange={() => {}}
                    tabs={[
                        { key: 'first', label: 'First tab' },
                        { key: 'second', label: 'Second tab' },
                    ]}
                />
            </Section>
            <Section title="Label">
                <LemonLabel>Field label</LemonLabel>
            </Section>
        </div>
    )
}

export const ReverseKitchenSink: StoryObj = {
    render: () => (
        <div className="grid grid-cols-3 gap-4">
            <div className="border rounded p-4" data-quill>
                <h4 className="mb-4">Quill today</h4>
                <QuillKitchenSink idPrefix="native" />
            </div>
            <div className="border rounded p-4" data-quill data-lemon-skin>
                <h4 className="mb-4">Quill + lemon skin (same code)</h4>
                <QuillKitchenSink idPrefix="skinned" />
            </div>
            <div className="border rounded p-4">
                <h4 className="mb-4">LemonUI (target)</h4>
                <LemonKitchenSink />
            </div>
        </div>
    ),
}
