import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { kafkaInspectorLogic } from './kafkaInspectorLogic'

export function KafkaInspectorTab(): JSX.Element {
    const { kafkaMessage } = useValues(kafkaInspectorLogic)

    return (
        <div>
            <h3 className="l3 mt-4">Kafka Inspector</h3>
            <div className="mb-4">Debug Kafka messages using the inspector tool.</div>
            <LemonDivider className="my-4" />
            <section>
                <div className="flex mb-3">
                    <Form logic={kafkaInspectorLogic} formKey="fetchKafkaMessage" enableFormOnSubmit>
                        <div className="grid grid-cols-12 gap-4">
                            <div className="col-span-4">
                                <Field name="topic">
                                    <LemonInput size="small" placeholder="Topic" />
                                </Field>
                            </div>
                            <div className="col-span-2">
                                <Field name="partition">
                                    <LemonInput size="small" placeholder="Partition" type="number" />
                                </Field>
                            </div>
                            <div className="col-span-2">
                                <Field name="offset">
                                    <LemonInput size="small" placeholder="Offset" type="number" />
                                </Field>
                            </div>
                            <div className="col-span-3">
                                <LemonButton data-attr="fetch-kafka-message-submit-button" type="primary">
                                    Fetch Message
                                </LemonButton>
                            </div>
                        </div>
                    </Form>
                </div>
            </section>
            <CodeSnippet language={Language.JSON}>
                {kafkaMessage ? JSON.stringify(kafkaMessage, null, 4) : '\n'}
            </CodeSnippet>
        </div>
    )
}
