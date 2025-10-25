import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useRef } from 'react'

import { IconArchive, IconShieldPeople } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonTree, LemonTreeProps } from './LemonTree'

type Story = StoryObj<typeof LemonTree>
const meta: Meta<typeof LemonTree> = {
    title: 'Lemon UI/Lemon Tree',
    component: LemonTree,
    args: {
        defaultNodeIcon: <IconArchive />,
        onFolderClick: (item) => {
            // This is not important, but nice to have
            // eslint-disable-next-line no-console
            console.log('clicked folder', item)
        },
        onItemClick: (item) => {
            // It's important to set focus to your desired content (in scene)
            // so that the keyboard navigation works
            // eslint-disable-next-line no-console
            console.log('clicked node', item)
        },
        showFolderActiveState: false,
        expandAllFolders: false,
        defaultSelectedFolderOrNodeId: 'pis_n3o4p',
        data: [
            {
                id: 'xxxxxxxxxxxxxx',
                name: 'Growth team',
                record: {
                    type: 'folder',
                    path: 'Growth team',
                },
                children: [
                    {
                        id: 'gsm_a1b2c',
                        name: 'Growth Support Metrics',
                        onClick: (open: boolean | undefined): void => {
                            // eslint-disable-next-line no-console
                            console.log('clicked growth support metrics', open)
                        },
                        record: {
                            type: 'file',
                            path: 'Growth team/Growth Support Metrics',
                        },
                    },
                    {
                        id: 'ssc_3d4e5',
                        name: 'Self-serve credits',
                        icon: <IconShieldPeople />,
                        disabledReason: "you're not cool enough",
                        record: {
                            type: 'file',
                            path: 'Growth team/Self-serve credits',
                        },
                    },
                    {
                        id: 'ot_f6g7h',
                        name: 'Onboarding things',
                        record: {
                            type: 'folder',
                            path: 'Growth team/Onboarding things',
                        },
                        children: [
                            {
                                id: 'cf_8i9j0',
                                name: 'Conversion funnel',
                                icon: <IconShieldPeople />,
                                record: {
                                    type: 'file',
                                    path: 'Growth team/Onboarding things/Conversion funnel',
                                },
                            },
                            {
                                id: 'mpu_k1l2m',
                                name: 'Multi-product usage',
                                icon: <IconShieldPeople />,
                                record: {
                                    type: 'file',
                                    path: 'Growth team/Onboarding things/Multi-product usage',
                                },
                            },
                            {
                                id: 'pis_n3o4p',
                                name: 'Post-install survey',
                                icon: <IconShieldPeople />,
                                record: {
                                    type: 'file',
                                    path: 'Growth team/Onboarding things/Post-install survey',
                                },
                            },
                        ],
                    },
                    {
                        id: 'ob2_q5r6s',
                        name: 'Onboarding 2.0',
                        disabledReason: "you're not cool enough",
                        record: {
                            type: 'folder',
                            path: 'Growth team/Onboarding 2.0',
                        },
                        children: [
                            {
                                id: 'hsc_t7u8v',
                                name: 'Hypothesis & success criteria',
                                icon: <IconShieldPeople />,
                                record: {
                                    type: 'file',
                                    path: 'Growth team/Onboarding 2.0/Hypothesis & success criteria',
                                },
                            },
                            {
                                id: 'ob2a_w9x0y',
                                name: 'Onboarding 2.0',
                                icon: <IconShieldPeople />,
                                record: {
                                    type: 'file',
                                    path: 'Growth team/Onboarding 2.0/Onboarding 2.0',
                                },
                            },
                            {
                                id: 'ob2b_z1a2b',
                                name: 'Onboarding 2.0',
                                icon: <IconShieldPeople />,
                                record: {
                                    type: 'file',
                                    path: 'Growth team/Onboarding 2.0/Onboarding 2.0',
                                },
                            },
                            {
                                id: 'ob2c_c3d4e',
                                name: 'Onboarding 2.0',
                                icon: <IconShieldPeople />,
                                record: {
                                    type: 'file',
                                    path: 'Growth team/Onboarding 2.0/Onboarding 2.0',
                                },
                            },
                        ],
                    },
                    {
                        id: 'bt_f5g6h',
                        name: 'Billing test',
                        record: {
                            type: 'folder',
                            path: 'Growth team/Billing test',
                        },
                        children: [
                            {
                                id: 'os_i7j8k',
                                name: 'other stuff',
                                icon: <IconShieldPeople />,
                                record: {
                                    type: 'file',
                                    path: 'Growth team/Billing test/other stuff',
                                },
                            },
                        ],
                    },
                ],
            },
            {
                id: 'et_l9m0n',
                name: 'Exec team',
                record: {
                    type: 'file',
                    path: 'Exec team',
                },
            },
            {
                id: 'wv_o1p2q',
                name: 'Website & vibes',
                record: {
                    type: 'file',
                    path: 'Website & vibes',
                },
            },
            {
                id: 'pa_r3s4t',
                name: 'Product analytics',
                record: {
                    type: 'file',
                    path: 'Product analytics',
                },
            },
            {
                id: 'uf_u5v6w',
                name: 'Unfiled',
                record: {
                    type: 'file',
                    path: 'Unfiled',
                },
            },
        ],
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof LemonTree> = (props: LemonTreeProps) => {
    const ref = useRef<HTMLDivElement>(null)
    return (
        <div className="deprecated-space-y-4">
            <Link to="https://posthog.com">PostHog</Link>
            <div className="deprecated-space-y-1">
                <p>
                    Keyboard navigation: when focused inside the tree, try [up] [right] [down] [left] [enter] [home]
                    [end]
                </p>
                <p>
                    Type-ahead search: when focused inside the tree, try typing the first few letters of a item and it
                    will focus it
                </p>
            </div>

            <div className="w-full h-full grid grid-cols-[250px_1fr]">
                <LemonTree {...props} contentRef={ref} />
                <main
                    className="p-4 focus-visible:ring-2 ring-accent ring-offset-1"
                    ref={ref}
                    role="main"
                    tabIndex={-1}
                >
                    <h1>Your scene here</h1>
                    <Link to="https://posthog.com">some content link</Link>
                </main>
            </div>
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}
