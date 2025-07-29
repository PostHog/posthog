import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import * as React from 'react'

import * as icons from '../icons'

const meta: Meta = {
    title: 'Lemon UI/Icons1',
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

// This is for actual Storybook users
export const Library: LibraryType = LibraryTemplate.bind({})
Library.tags = ['autodocs', 'test-skip']

// These are just for snapshots. As opposed to the full library, the stories below are segmented by the first letter
// of the icon name, which greatly optimizes both the UX and storage aspects of diffing snapshots.
export const ShelfA: LibraryType = LibraryTemplate.bind({})
ShelfA.args = { letter: 'a' }
ShelfA.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfB: LibraryType = LibraryTemplate.bind({})
ShelfB.args = { letter: 'b' }
ShelfB.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfC: LibraryType = LibraryTemplate.bind({})
ShelfC.args = { letter: 'c' }
ShelfC.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfD: LibraryType = LibraryTemplate.bind({})
ShelfD.args = { letter: 'd' }
ShelfD.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfE: LibraryType = LibraryTemplate.bind({})
ShelfE.args = { letter: 'e' }
ShelfE.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfF: LibraryType = LibraryTemplate.bind({})
ShelfF.args = { letter: 'f' }
ShelfF.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfG: LibraryType = LibraryTemplate.bind({})
ShelfG.args = { letter: 'g' }
ShelfG.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfH: LibraryType = LibraryTemplate.bind({})
ShelfH.args = { letter: 'h' }
ShelfH.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
export const ShelfI: LibraryType = LibraryTemplate.bind({})
ShelfI.args = { letter: 'i' }
ShelfI.parameters = { testOptions: { snapshotTargetSelector: '.LemonTable tbody' } }
