import { IconArchive, IconShieldPeople } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useRef } from 'react'

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
        onNodeClick: (item) => {
            // It's important to set focus to your desired content (in scene)
            // so that the keyboard navigation works
            // eslint-disable-next-line no-console
            console.log('clicked node', item)
        },
        showFolderActiveState: false,
        expandAllFolders: false,
        // defaultSelectedFolderOrNodeId: 'pis_n3o4p',
        data: [
            {
                id: 'gt_7d8f9',
                name: 'Growth team',
                children: [
                    {
                        id: 'gsm_a1b2c',
                        name: 'Growth Support Metrics',
                        onClick: (open: boolean | undefined): void => {
                            // eslint-disable-next-line no-console
                            console.log('clicked growth support metrics', open)
                        },
                    },
                    {
                        id: 'ssc_3d4e5',
                        name: 'Self-serve credits',
                        icon: <IconShieldPeople />,
                        disabledReason: "you're not cool enough",
                    },
                    {
                        id: 'ot_f6g7h',
                        name: 'Onboarding things',
                        children: [
                            {
                                id: 'cf_8i9j0',
                                name: 'Conversion funnel',
                                icon: <IconShieldPeople />,
                            },
                            {
                                id: 'mpu_k1l2m',
                                name: 'Multi-product usage',
                                icon: <IconShieldPeople />,
                            },
                            {
                                id: 'pis_n3o4p',
                                name: 'Post-install survey',
                                icon: <IconShieldPeople />,
                            },
                        ],
                    },
                    {
                        id: 'ob2_q5r6s',
                        name: 'Onboarding 2.0',
                        disabledReason: "you're not cool enough",
                        children: [
                            {
                                id: 'hsc_t7u8v',
                                name: 'Hypothesis & success criteria',
                                icon: <IconShieldPeople />,
                            },
                            {
                                id: 'ob2a_w9x0y',
                                name: 'Onboarding 2.0',
                                icon: <IconShieldPeople />,
                            },
                            {
                                id: 'ob2b_z1a2b',
                                name: 'Onboarding 2.0',
                                icon: <IconShieldPeople />,
                            },
                            {
                                id: 'ob2c_c3d4e',
                                name: 'Onboarding 2.0',
                                icon: <IconShieldPeople />,
                            },
                        ],
                    },
                    {
                        id: 'bt_f5g6h',
                        name: 'Billing test',
                        children: [
                            {
                                id: 'os_i7j8k',
                                name: 'other stuff',
                                icon: <IconShieldPeople />,
                            },
                        ],
                    },
                ],
            },
            {
                id: 'et_l9m0n',
                name: 'Exec team',
            },
            {
                id: 'wv_o1p2q',
                name: 'Website & vibes',
            },
            {
                id: 'pa_r3s4t',
                name: 'Product analytics',
            },
            {
                id: 'uf_u5v6w',
                name: 'Unfilled',
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
                    className="p-4 focus-visible:ring-2 ring-accent-primary ring-offset-1"
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
