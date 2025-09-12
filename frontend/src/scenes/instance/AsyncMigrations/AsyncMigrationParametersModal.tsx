import { useActions } from 'kea'
import { Field, Form } from 'kea-forms'
import { useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { asyncMigrationParameterFormLogic } from 'scenes/instance/AsyncMigrations/asyncMigrationParameterFormLogic'
import { AsyncMigrationModalProps, asyncMigrationsLogic } from 'scenes/instance/AsyncMigrations/asyncMigrationsLogic'

export function AsyncMigrationParametersModal(props: AsyncMigrationModalProps): JSX.Element {
    const { closeAsyncMigrationsModal } = useActions(asyncMigrationsLogic)

    const [collapsed, setCollapsed] = useState(true)

    return (
        <LemonModal title="" onClose={closeAsyncMigrationsModal} isOpen={true} simple>
            <Form
                logic={asyncMigrationParameterFormLogic}
                props={props}
                formKey="parameters"
                enableFormOnSubmit
                id="async-migration-parameters-form"
                className="LemonModal__layout"
            >
                <LemonModal.Header>
                    <h3>Advanced migration configuration</h3>
                </LemonModal.Header>
                <LemonModal.Content>
                    <p>
                        This async migration allows tuning parameters used in the async migration.
                        {collapsed && (
                            <>
                                <br />
                                <Link
                                    onClick={() => {
                                        setCollapsed(!collapsed)
                                    }}
                                >
                                    Show advanced configuration
                                </Link>
                            </>
                        )}
                    </p>

                    <AnimatedCollapsible collapsed={collapsed}>
                        {Object.entries(props.migration.parameter_definitions).map(
                            ([parameterName, [defaultValue, parameterDescription]]) => (
                                <Field name={parameterName} key={parameterName} label={<>{parameterDescription}</>}>
                                    {/* TODO: Send the parameter type from the backend */}
                                    <LemonInput type={typeof defaultValue === 'number' ? 'number' : 'text'} />
                                </Field>
                            )
                        )}
                    </AnimatedCollapsible>
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton
                        form="async-migration-parameters-form"
                        type="secondary"
                        data-attr="async-migration-parameters-cancel"
                        className="mr-2"
                        onClick={closeAsyncMigrationsModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="async-migration-parameters-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="async-migration-parameters-submit"
                    >
                        Run migration
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
