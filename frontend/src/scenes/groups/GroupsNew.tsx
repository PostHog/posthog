import { useActions, useValues } from 'kea'
import { Form, Group, capitalizeFirstLetter } from 'kea-forms'
import { router } from 'kea-router'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { GroupsNewLogicProps, groupsNewLogic } from 'scenes/groups/groupsNewLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport<GroupsNewLogicProps> = {
    component: GroupsNew,
    logic: groupsNewLogic,
    paramsToProps: ({ params: { groupTypeIndex } }) => ({
        groupTypeIndex: parseInt(groupTypeIndex ?? '0'),
    }),
}

export function GroupsNew(): JSX.Element {
    const { logicProps, group, groupTypeName, groupTypeNamePlural } = useValues(groupsNewLogic)
    const { addFormProperty, removeFormProperty, setGroupValue } = useActions(groupsNewLogic)

    return (
        <Form id="group" logic={groupsNewLogic} props={logicProps} formKey="group" enableFormOnSubmit>
            <SceneContent className="groups-new">
                <SceneTitleSection
                    name={`New ${groupTypeName} group`}
                    resourceType={{ type: 'group' }}
                    actions={
                        <>
                            <LemonButton
                                data-attr="cancel-group"
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    router.actions.push(urls.groups(logicProps.groupTypeIndex))
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="primary"
                                data-attr="save-group"
                                htmlType="submit"
                                form="group"
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                    forceBackTo={{
                        name: `People / Groups / ${capitalizeFirstLetter(groupTypeNamePlural)}`,
                        path: urls.groups(logicProps.groupTypeIndex),
                        key: 'groups',
                    }}
                />
                <div className="deprecated-space-y-2 max-w-200 gap-4">
                    <div className="flex gap-4 flex-wrap">
                        <div className="flex-1">
                            <LemonField name="name" label="Name">
                                <LemonInput data-attr="group-name" />
                            </LemonField>
                        </div>
                        <div className="flex-1">
                            <LemonField name="group_key" label="ID">
                                <LemonInput data-attr="group-key" />
                            </LemonField>
                        </div>
                    </div>
                    <LemonDivider className="my-4" />
                </div>
                <div className="deprecated-space-y-2 max-w-214 gap-4">
                    <div className="mt-4">
                        <h3 className="text-md font-medium mb-2">Properties</h3>

                        {group.customProperties && group.customProperties.length > 0 && (
                            <div className="flex gap-4 mb-2 text-s font-medium">
                                <div className="flex-1">Name</div>
                                <div className="flex-1">Type</div>
                                <div className="flex-1">Value</div>
                                <div className="w-8" /> {/* Space for trash button */}
                            </div>
                        )}

                        {group.customProperties &&
                            group.customProperties.map((_, index: number) => (
                                <Group key={index} name={['customProperties', index]}>
                                    <div className="flex gap-4 mb-2 items-start">
                                        <div className="flex-1">
                                            <LemonField name="name">
                                                <LemonInput placeholder="e.g. is_subscribed" />
                                            </LemonField>
                                        </div>
                                        <div className="flex-1">
                                            <LemonField name="type">
                                                <LemonSegmentedButton
                                                    onChange={(value: 'string' | 'boolean') => {
                                                        const currentProperties = group.customProperties || []
                                                        const updatedProperties = currentProperties.map((prop, i) =>
                                                            i === index
                                                                ? {
                                                                      ...prop,
                                                                      type: value,
                                                                      value: value === 'string' ? '' : 'true',
                                                                  }
                                                                : prop
                                                        )
                                                        setGroupValue('customProperties', updatedProperties)
                                                    }}
                                                    value={group.customProperties?.[index]?.type || 'string'}
                                                    options={[
                                                        {
                                                            value: 'string',
                                                            label: 'Text or Number',
                                                        },
                                                        {
                                                            value: 'boolean',
                                                            label: 'Boolean or Null',
                                                        },
                                                    ]}
                                                    size="small"
                                                />
                                            </LemonField>
                                        </div>
                                        <div className="flex-1">
                                            <LemonField name="value">
                                                {group.customProperties?.[index]?.type === 'boolean' ? (
                                                    <LemonSegmentedButton
                                                        onChange={(value: string) => {
                                                            const currentProperties = group.customProperties || []
                                                            const updatedProperties = currentProperties.map(
                                                                (prop, i) => (i === index ? { ...prop, value } : prop)
                                                            )
                                                            setGroupValue('customProperties', updatedProperties)
                                                        }}
                                                        value={group.customProperties?.[index]?.value || 'true'}
                                                        options={[
                                                            {
                                                                value: 'true',
                                                                label: 'True',
                                                            },
                                                            {
                                                                value: 'false',
                                                                label: 'False',
                                                            },
                                                            {
                                                                value: 'null',
                                                                label: 'Null',
                                                            },
                                                        ]}
                                                        size="small"
                                                    />
                                                ) : (
                                                    <LemonInput placeholder="e.g. subscription_tier" />
                                                )}
                                            </LemonField>
                                        </div>
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            type="secondary"
                                            status="danger"
                                            onClick={() => removeFormProperty(index)}
                                            data-attr={`remove-property-${index}`}
                                        />
                                    </div>
                                </Group>
                            ))}

                        <LemonButton
                            icon={<IconPlus />}
                            type="secondary"
                            onClick={addFormProperty}
                            data-attr="add-property"
                        >
                            Add property
                        </LemonButton>
                    </div>
                </div>
            </SceneContent>
        </Form>
    )
}
