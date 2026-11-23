import { Button, Card, CardContent, Heading, Text } from '@posthog/quill'

export function QuillReauthenticationRequired({ onReauthenticate }: { onReauthenticate: () => void }): JSX.Element {
    return (
        <Card className="max-w-3xl">
            <CardContent className="flex flex-col items-start gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Re-authentication required
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    This settings area contains sensitive information, so we need you to re-authenticate before
                    continuing.
                </Text>
                <Button variant="primary" onClick={onReauthenticate}>
                    Re-authenticate
                </Button>
            </CardContent>
        </Card>
    )
}
