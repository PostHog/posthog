import { Meta, StoryFn, StoryObj } from '@storybook/react'
import * as React from 'react'

import { IconDashboard } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import * as icons from '../icons'

const { IconWithCount } = icons

const meta: Meta = {
    title: 'Lemon UI/Icons3',
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
    .filter(([key]) => key !== 'IconWithCount' && key !== 'IconWithBadge')
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
        <div className="deprecated-space-y-2">
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

export const ShelfS: LibraryType = LibraryTemplate.bind({})
ShelfS.args = { letter: 's' }
ShelfS.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfT: LibraryType = LibraryTemplate.bind({})
ShelfT.args = { letter: 't' }
ShelfT.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfU: LibraryType = LibraryTemplate.bind({})
ShelfU.args = { letter: 'u' }
ShelfU.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfV: LibraryType = LibraryTemplate.bind({})
ShelfV.args = { letter: 'v' }
ShelfV.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfW: LibraryType = LibraryTemplate.bind({})
ShelfW.args = { letter: 'w' }
ShelfW.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfX: LibraryType = LibraryTemplate.bind({})
ShelfX.args = { letter: 'x' }
ShelfX.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfY: LibraryType = LibraryTemplate.bind({})
ShelfY.args = { letter: 'y' }
ShelfY.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfZ: LibraryType = LibraryTemplate.bind({})
ShelfZ.args = { letter: 'z' }
ShelfZ.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfOther: LibraryType = LibraryTemplate.bind({})
ShelfOther.args = { letter: null }
ShelfOther.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }

export function IconWithCountBubble(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-accent p-1">
            <IconWithCount count={7}>
                <IconDashboard />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountHidingZero(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-accent p-1">
            <IconWithCount count={0} showZero={false}>
                <IconDashboard />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountShowingZero(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-accent p-1">
            <IconWithCount count={0} showZero={true}>
                <IconDashboard />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountOverflowing(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-accent p-1">
            <IconWithCount count={11} showZero={true}>
                <IconDashboard />
            </IconWithCount>
        </span>
    )
}
