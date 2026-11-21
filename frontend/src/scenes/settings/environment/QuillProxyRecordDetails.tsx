import { useActions, useValues } from 'kea'

import { Button, Input, Tabs, TabsContent, TabsList, TabsTrigger, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { DomainConnectBanner } from 'lib/components/DomainConnect'

import { ProxyRecord, canConfigureRootRedirect, proxyLogic } from './proxyLogic'
import { QuillProxyDiagnosticReport } from './QuillProxyDiagnosticReport'

export function QuillProxyRecordDetails({ record }: { record: ProxyRecord }): JSX.Element {
    const { diagnosticReports, recordActiveTabs, rootRedirectDrafts, proxyRecordsLoading } = useValues(proxyLogic)
    const { setRecordActiveTab, setRootRedirectDraft, updateRootRedirect } = useActions(proxyLogic)

    const report = diagnosticReports[record.id]
    const activeKey = recordActiveTabs[record.id] ?? 'cname'
    const rootRedirectDraft = rootRedirectDrafts[record.id] ?? record.root_redirect_url ?? ''
    const showRootRedirect = canConfigureRootRedirect(record)

    return (
        <div className="flex flex-col gap-2">
            <Tabs value={activeKey} onValueChange={(key) => setRecordActiveTab(record.id, String(key))}>
                <TabsList variant="line">
                    <TabsTrigger value="cname">CNAME</TabsTrigger>
                    {showRootRedirect && <TabsTrigger value="root-redirect">Root redirect</TabsTrigger>}
                    {report && <TabsTrigger value="diagnosis">Diagnosis</TabsTrigger>}
                </TabsList>
                <TabsContent value="cname" className="pt-2">
                    <CodeSnippet key={record.id} language={Language.HTTP}>
                        {record.target_cname}
                    </CodeSnippet>
                </TabsContent>
                {showRootRedirect && (
                    <TabsContent value="root-redirect" className="pt-2">
                        <div className="flex max-w-160 flex-col items-start gap-2">
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Redirect visits to <code>{`https://${record.domain}/`}</code> to another HTTPS URL. This
                                does not affect event ingestion or other proxy paths.
                            </Text>
                            <Input
                                type="url"
                                aria-label="Root redirect URL"
                                value={rootRedirectDraft}
                                onChange={(event) => setRootRedirectDraft(record.id, event.target.value)}
                                placeholder="https://www.example.com/"
                            />
                            <Button
                                variant="primary"
                                onClick={() =>
                                    updateRootRedirect({ id: record.id, rootRedirectUrl: rootRedirectDraft })
                                }
                                loading={proxyRecordsLoading}
                                disabledReason={
                                    rootRedirectDraft === (record.root_redirect_url ?? '')
                                        ? 'No changes to save'
                                        : undefined
                                }
                            >
                                Save redirect
                            </Button>
                        </div>
                    </TabsContent>
                )}
                {report && (
                    <TabsContent value="diagnosis" className="pt-2">
                        <QuillProxyDiagnosticReport report={report} />
                    </TabsContent>
                )}
            </Tabs>
            {record.status === 'waiting' && (
                <DomainConnectBanner
                    logicKey={`proxy-${record.id}`}
                    domain={record.domain}
                    context="proxy"
                    proxyRecordId={record.id}
                />
            )}
        </div>
    )
}
