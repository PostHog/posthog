import React, { useState } from 'react'
import { useActions } from 'kea'
import { AsyncMigrationModalProps, asyncMigrationsLogic } from 'scenes/instance/AsyncMigrations/asyncMigrationsLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { asyncMigrationParameterFormLogic } from 'scenes/instance/AsyncMigrations/asyncMigrationParameterFormLogic'
import { Field, Form } from 'kea-forms'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { LemonModal } from 'lib/components/LemonModal'

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
                                <a
                                    onClick={() => {
                                        setCollapsed(!collapsed)
                                    }}
                                >
                                    Click here to show advanced configuration.
                                </a>
                            </>
                        )}
                    </p>

                    <AnimatedCollapsible collapsed={collapsed}>
                        {Object.keys(props.migration.parameter_definitions).map((key) => (
                            <Field name={key} key={key} label={<>{props.migration.parameter_definitions[key][1]}</>}>
                                <LemonInput type="number" />
                            </Field>
                        ))}
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
