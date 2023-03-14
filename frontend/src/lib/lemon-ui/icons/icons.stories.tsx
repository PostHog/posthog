import * as React from 'react'
import * as icons from './icons'
import { Meta } from '@storybook/react'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { IconMagnifier } from './icons'
import Fuse from 'fuse.js'
import { useEffect } from 'react'

const { IconGauge, IconWithCount } = icons

interface IconDefinition {
    name: string
    icon: (...args: any[]) => JSX.Element
}

const allIcons: IconDefinition[] = Object.entries(icons)
    .filter(([key]) => key !== 'IconWithCount')
    .map(([key, Icon]) => ({ name: key, icon: Icon }))
    .sort((a, b) => a.name.localeCompare(b.name))

const fuse = new Fuse(allIcons, {
    keys: ['name'],
    threshold: 0.3,
})

export default {
    title: 'Lemon UI/Icons',
    parameters: {
        options: { showPanel: false },
        testOptions: { skip: true }, // There are too many icons, the snapshots are huge in table form
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
} as Meta

export function Library(): JSX.Element {
    const [showBorder, setShowBorder] = React.useState(true)
    const [search, setSearch] = React.useState('')
    const [filteredIcons, setFilteredIcons] = React.useState(allIcons)

    useEffect(() => {
        if (search.trim() !== '') {
            setFilteredIcons(
                fuse
                    .search(search)
                    .map((result) => result.item)
                    .sort((a, b) => a.name.localeCompare(b.name))
            )
        }
    }, [search])

    return (
        <div className="space-y-2">
            <div className={'flex flex-row justify-between'}>
                <LemonCheckbox bordered checked={showBorder} onChange={setShowBorder} label="Show border" />
                <LemonInput value={search} onChange={setSearch} placeholder="Filter" prefix={<IconMagnifier />} />
            </div>
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
            />
        </div>
    )
}

export function IconWithCountBubble(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-primary">
            <IconWithCount count={7}>
                <IconGauge />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountHidingZero(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-primary">
            <IconWithCount count={0} showZero={false}>
                <IconGauge />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountShowingZero(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-primary">
            <IconWithCount count={0} showZero={true}>
                <IconGauge />
            </IconWithCount>
        </span>
    )
}

export function IconWithCountOverflowing(): JSX.Element {
    return (
        <span className="inline-flex text-2xl border border-primary">
            <IconWithCount count={11} showZero={true}>
                <IconGauge />
            </IconWithCount>
        </span>
    )
}
