import * as React from 'react'
import * as icons from './icons'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

const { IconGauge, IconWithCount } = icons

const meta: Meta = {
    title: 'Lemon UI/Icons',
    parameters: {
        docs: {
            description: {
                component: `

[Related Figma area](https://www.figma.com/file/Y9G24U4r04nEjIDGIEGuKI/PostHog-Design-System-One?node-id=3139%3A1388)

Lemon Icons are generally [Material Icons](https://fonts.google.com/icons) with some matching in-house additions. 
All should be based on a 24px (1.5rem) square viewbox, with icon contents fitting into a 20px (1.25rem) or smaller square. 

When adding new icons from Figma please make sure to:
- [ ] Export the item as an SVG using the 24x24 frame surrounding it
- [ ] Follow the existing \`IconFoo\` naming convention and use the \`<SvgIcon>\` component instead of \`<svg>\`
- [ ] Ensure all colors in the SVG are set to \`currentColor\` so that themes can be applied
`,
            },
        },
    },
    tags: ['autodocs'],
}
export default meta

interface IconDefinition {
    name: string
    icon: (...args: any[]) => JSX.Element
}

const allIcons: IconDefinition[] = Object.entries(icons)
    .filter(([key]) => key !== 'IconWithCount')
    .map(([key, Icon]) => ({ name: key, icon: Icon }))
    .sort((a, b) => a.name.localeCompare(b.name))

type LibraryType = StoryObj<{ letter?: string | null }>
const LibraryTemplate: StoryFn<{ letter?: string | null }> = ({ letter }) => {
    const [showBorder, setShowBorder] = React.useState(true)
    const filteredIcons =
        letter === undefined
            ? allIcons
            : letter !== null
            ? allIcons.filter((icon) => icon.name.replace('Icon', '').toLowerCase().startsWith(letter))
            : allIcons.filter((icon) => !icon.name.replace('Icon', '').toLowerCase().match(/[a-z]/))

    return (
        <div className="space-y-2">
            <LemonCheckbox bordered checked={showBorder} onChange={setShowBorder} label="Show border" />
            <LemonTable
                dataSource={filteredIcons}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        dataIndex: 'name',
                        render: function RenderName(name) {
                            return <code>{`<${name as string} />`}</code>
                        },
                    },
                    {
                        title: 'Icon',
                        key: 'icon',
                        dataIndex: 'icon',
                        render: function RenderIcon(Icon) {
                            Icon = Icon as IconDefinition['icon']
                            return (
                                <Icon
                                    style={{
                                        fontSize: '1.5rem',
                                        boxShadow: showBorder ? '0px 0px 1px 1px red' : null,
                                    }}
                                />
                            )
                        },
                    },

                    {
                        title: 'In Button',
                        key: 'button-icon',
                        dataIndex: 'icon',
                        render: function RenderButton(Icon) {
                            Icon = Icon as IconDefinition['icon']
                            return (
                                <LemonButton type="secondary" icon={<Icon />}>
                                    Button
                                </LemonButton>
                            )
                        },
                    },
                ]}
                emptyState={letter ? `No icons start with the letter ${letter.toUpperCase()}` : 'No icons'}
            />
        </div>
    )
}

export const Library: LibraryType = {
    render: LibraryTemplate,
    parameters: { testOptions: { skip: true } },
}

export const ShelfA: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'a' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfB: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'b' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfC: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'c' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfD: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'd' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfE: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'e' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfF: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'f' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfG: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'g' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfH: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'h' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfI: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'i' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfJ: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'j' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfK: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'k' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfL: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'l' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfM: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'm' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfN: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'n' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfO: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'o' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfP: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'p' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfQ: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'q' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfR: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'r' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfS: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 's' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfT: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 't' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfU: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'u' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfV: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'v' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfW: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'w' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfX: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'x' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfY: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'y' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfZ: LibraryType = {
    render: LibraryTemplate,
    args: { letter: 'z' },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export const ShelfOther: LibraryType = {
    render: LibraryTemplate,
    args: { letter: null },
    parameters: { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } },
}

export function IconWithCountBubble(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-primary p-1">
            <IconWithCount count={7}>
                <IconGauge />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountHidingZero(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-primary p-1">
            <IconWithCount count={0} showZero={false}>
                <IconGauge />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountShowingZero(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-primary p-1">
            <IconWithCount count={0} showZero={true}>
                <IconGauge />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountOverflowing(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-primary p-1">
            <IconWithCount count={11} showZero={true}>
                <IconGauge />
            </IconWithCount>
        </span>
    )
}
