import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuSection, LemonSwitch } from '@posthog/lemon-ui'

import { customerProfileLogic } from '../customerProfileLogic'

export function CustomerProfileMenu(): JSX.Element | null {
    const { changed, isProfileConfigEnabled, defaultContent, content } = useValues(customerProfileLogic)
    const { removeNode, addNode, resetToDefaults, saveChanges } = useActions(customerProfileLogic)

    const handleChange = (nodeType: string | undefined, checked: boolean): void => {
        if (nodeType === undefined) {
            return
        }
        checked ? addNode(nodeType) : removeNode(nodeType)
    }

    const items: LemonMenuSection[] = [
        {
            title: 'Visible tiles',
            items: defaultContent.map((node) => ({
                label: () => (
                    <LemonSwitch
                        key={node.type}
                        label={node?.attrs?.title || node.type}
                        checked={content.some((c) => c.type === node.type)}
                        onChange={(checked) => handleChange(node?.type, checked)}
                        fullWidth
                    />
                ),
            })),
        },
    ]

    if (!isProfileConfigEnabled) {
        return null
    }

    return (
        <div className="flex flex-row items-center">
            <LemonMenu items={items} closeOnClickInside={false}>
                <LemonButton type="secondary" icon={<IconGear />} children="Edit profile" sideIcon={null} />
            </LemonMenu>
            {changed && (
                <>
                    <LemonButton
                        type="primary"
                        className="ml-2"
                        children="Save changes"
                        sideIcon={null}
                        onClick={() => saveChanges()}
                    />
                    <LemonButton
                        type="secondary"
                        className="ml-2"
                        children="Cancel"
                        sideIcon={null}
                        onClick={() => resetToDefaults()}
                    />
                </>
            )}
        </div>
    )
}
