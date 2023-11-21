import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonButton, LemonButtonProps } from './LemonButton'
import { capitalizeFirstLetter } from 'lib/utils'
import { setFeatureFlags } from '~/mocks/browser'
import { FEATURE_FLAGS } from 'lib/constants'
import { useActions } from 'kea'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { useEffect } from 'react'

type Story = StoryObj<typeof LemonButton>

const types: LemonButtonProps['type'][] = ['primary', 'secondary', 'tertiary']

const meta: Meta<typeof LemonButton> = {
    title: 'Lemon UI/Lemon Button 3000',
    component: LemonButton,
    tags: ['autodocs'],
}

export default meta

const BasicButton: StoryFn<typeof LemonButton> = (props: LemonButtonProps) => {
    return <LemonButton {...props} />
}

const TypesTemplate = ({ darkMode }: { darkMode: boolean }) => {
    const { overrideTheme } = useActions(themeLogic)

    setFeatureFlags([FEATURE_FLAGS.POSTHOG_3000])

    useEffect(() => {
        overrideTheme(darkMode)
    }, [])

    return (
        <div className={'flex gap-2 border rounded-lg p-2 flex-wrap'}>
            {types.map((type) => (
                <BasicButton key={type} type={type}>
                    {capitalizeFirstLetter(type || 'default')}
                </BasicButton>
            ))}
        </div>
    )
}

export const LightMode = () => <TypesTemplate darkMode={false} />
export const DarkMode = () => <TypesTemplate darkMode />

export const Hover: Story = BasicButton
Hover.args = { children: 'Click me', type: 'primary' }
Hover.parameters = { pseudo: { hover: ['.LemonButton'] } }

// export const Active: Story = TypesTemplate.bind({})
// Active.args = Default.args
// Active.parameters = { pseudo: { active: ['.LemonButton'] } }
