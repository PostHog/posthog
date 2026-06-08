import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'

import IconPostgres from 'public/services/postgres.png'

import { PostgreSQLSetupModalLogicProps, postgreSQLSetupModalLogic } from './postgreSQLSetupModalLogic'

export const PostgreSQLSetupModal = (props: PostgreSQLSetupModalLogicProps): JSX.Element => {
    const { postgreSQLIntegration, isPostgreSQLIntegrationSubmitting } = useValues(postgreSQLSetupModalLogic(props))
    const { submitPostgreSQLIntegration, setPostgreSQLIntegrationValue } = useActions(postgreSQLSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <img src={IconPostgres} alt="PostgreSQL" className="w-6 h-6" />
                    <span>Configure PostgreSQL integration</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={postgreSQLSetupModalLogic} props={props} formKey="postgreSQLIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField name="host" label="Host">
                        <LemonInput placeholder="my-host" />
                    </LemonField>

                    <LemonField name="port" label="Port">
                        <LemonInput placeholder="5432" type="number" min="0" max="65535" />
                    </LemonField>

                    <LemonField name="user" label="User">
                        <LemonInput placeholder="postgres" />
                    </LemonField>

                    <LemonField name="password" label="Password">
                        <LemonInput type="password" />
                    </LemonField>

                    <LemonField name="ssl_mode" label="Verify server identity?">
                        <LemonSelect
                            options={[
                                { value: 'no', label: 'No' },
                                { value: 'verify-ca', label: 'Verify certificate authority' },
                                { value: 'verify-full', label: 'Verify certificate authority and server hostname' },
                            ]}
                        />
                    </LemonField>

                    {postgreSQLIntegration.ssl_mode !== 'no' && (
                        <>
                            <LemonField name="use_system_ca">
                                {({ value, onChange }) => (
                                    <LemonCheckbox
                                        bordered
                                        checked={!!value}
                                        onChange={onChange}
                                        label="Use the system certificate authorities"
                                    />
                                )}
                            </LemonField>

                            {!postgreSQLIntegration.use_system_ca && (
                                <LemonField name="ssl_root_cert" label="Root certificate">
                                    {() => (
                                        <LemonFileInput
                                            accept=".crt,.pem,.cer,.ca-bundle"
                                            multiple={false}
                                            onChange={(files) => {
                                                if (files[0]) {
                                                    void files[0]
                                                        .text()
                                                        .then((text) =>
                                                            setPostgreSQLIntegrationValue('ssl_root_cert', text)
                                                        )
                                                } else {
                                                    setPostgreSQLIntegrationValue('ssl_root_cert', null)
                                                }
                                            }}
                                        />
                                    )}
                                </LemonField>
                            )}
                        </>
                    )}

                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isPostgreSQLIntegrationSubmitting}
                            onClick={submitPostgreSQLIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
