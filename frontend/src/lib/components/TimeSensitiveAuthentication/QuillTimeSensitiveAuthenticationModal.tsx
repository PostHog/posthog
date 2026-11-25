import { useActions, useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    FieldSeparator,
    Input,
    Spinner,
    Text,
} from '@posthog/quill'

import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'

import { SSOEnforcedLoginButton, SocialLoginButtons } from '../SocialLoginButton/SocialLoginButton'
import { QuillSetPasswordLinkPrompt } from './QuillSetPasswordLinkPrompt'
import { timeSensitiveAuthenticationLogic } from './timeSensitiveAuthenticationLogic'

export function QuillTimeSensitiveAuthenticationModal({
    showPassword,
    showSetPasswordLink,
    extraQueryParams,
}: {
    showPassword: boolean
    showSetPasswordLink: boolean
    extraQueryParams: Record<string, string>
}): JSX.Element {
    const {
        showAuthenticationModal,
        isReauthenticationSubmitting,
        twoFactorRequired,
        user,
        precheckResponse,
        precheckResponseLoading,
        passkey2FALoading,
        passkeysAvailable,
        totpAvailable,
        reauthenticationPrompt,
    } = useValues(timeSensitiveAuthenticationLogic)
    const { submitReauthentication, setDismissedReauthentication, beginPasskey2FA, beginSsoReauthentication } =
        useActions(timeSensitiveAuthenticationLogic)

    const ssoEnforcement = precheckResponse?.sso_enforcement

    return (
        <Dialog
            open={showAuthenticationModal}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    setDismissedReauthentication(true)
                }
            }}
        >
            {/* Matches the Lemon re-auth modal's layer, so the prompt opens above any modal that triggered it. */}
            <DialogContent className="[--quill-z-modal:1169]" overlayClassName="[--quill-z-overlay:1169]">
                <DialogHeader>
                    <DialogTitle>{reauthenticationPrompt?.title ?? 'Re-authenticate for security'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Text size="xs" render={<p className="m-0" />}>
                            {reauthenticationPrompt?.description ?? (
                                <>
                                    Before accessing and changing sensitive settings, we ask you
                                    to&nbsp;re-authenticate. Just to ensure you are you!
                                </>
                            )}
                        </Text>

                        {precheckResponseLoading ? (
                            <div className="flex justify-center">
                                <Spinner />
                            </div>
                        ) : (
                            <>
                                {showPassword ? (
                                    <Form
                                        logic={timeSensitiveAuthenticationLogic}
                                        formKey="reauthentication"
                                        className="flex flex-col gap-4"
                                        enableFormOnSubmit
                                    >
                                        {!twoFactorRequired ? (
                                            <>
                                                {/* Password managers match a saved login by username, so a lone password field gets a generated password instead */}
                                                <input
                                                    type="email"
                                                    name="email"
                                                    autoComplete="username"
                                                    value={user?.email || ''}
                                                    readOnly
                                                    tabIndex={-1}
                                                    aria-hidden
                                                    className="sr-only"
                                                />
                                                <KeaField name="password" noStyle>
                                                    {({ id, value, onChange, error }) => (
                                                        <Field data-invalid={error ? true : undefined}>
                                                            <FieldLabel htmlFor={id}>Password</FieldLabel>
                                                            <Input
                                                                id={id}
                                                                type="password"
                                                                className="ph-ignore-input"
                                                                data-attr="password"
                                                                autoComplete="current-password"
                                                                autoFocus
                                                                value={value ?? ''}
                                                                onChange={(event) => onChange(event.target.value)}
                                                            />
                                                            {error && <FieldError>{error}</FieldError>}
                                                        </Field>
                                                    )}
                                                </KeaField>
                                            </>
                                        ) : (
                                            <>
                                                {passkeysAvailable && (
                                                    <Button
                                                        variant="primary"
                                                        type="button"
                                                        size="lg"
                                                        className="w-full"
                                                        onClick={() => beginPasskey2FA()}
                                                        loading={passkey2FALoading}
                                                    >
                                                        <img
                                                            src={passkeyLogo}
                                                            alt="Passkey"
                                                            className="object-contain size-6"
                                                        />
                                                        Use passkey
                                                    </Button>
                                                )}

                                                {passkeysAvailable && totpAvailable && (
                                                    <FieldSeparator>Or</FieldSeparator>
                                                )}

                                                {totpAvailable && (
                                                    <KeaField name="token" noStyle>
                                                        {({ id, value, onChange, error }) => (
                                                            <Field data-invalid={error ? true : undefined}>
                                                                <FieldLabel htmlFor={id}>
                                                                    Authenticator token
                                                                </FieldLabel>
                                                                <Input
                                                                    id={id}
                                                                    className="ph-ignore-input"
                                                                    autoFocus={!passkeysAvailable}
                                                                    data-attr="token"
                                                                    placeholder="123456"
                                                                    inputMode="numeric"
                                                                    autoComplete="one-time-code"
                                                                    value={value ?? ''}
                                                                    onChange={(event) => onChange(event.target.value)}
                                                                />
                                                                {error && <FieldError>{error}</FieldError>}
                                                            </Field>
                                                        )}
                                                    </KeaField>
                                                )}

                                                {!passkeysAvailable && !totpAvailable && (
                                                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                                        No 2FA methods available. Please contact support.
                                                    </Text>
                                                )}
                                            </>
                                        )}
                                    </Form>
                                ) : null}

                                {!ssoEnforcement ? (
                                    <div className="flex flex-col gap-2">
                                        <SocialLoginButtons
                                            caption={showPassword ? 'Or re-authenticate with' : undefined}
                                            extraQueryParams={extraQueryParams}
                                            onProviderClick={beginSsoReauthentication}
                                            showPasskey={true}
                                        />
                                        {precheckResponse?.saml_available ? (
                                            <SSOEnforcedLoginButton
                                                provider="saml"
                                                email={user!.email}
                                                size="medium"
                                                extraQueryParams={extraQueryParams}
                                                onProviderClick={beginSsoReauthentication}
                                            />
                                        ) : null}
                                        {precheckResponse?.oidc_available ? (
                                            <SSOEnforcedLoginButton
                                                provider="oidc"
                                                email={user!.email}
                                                size="medium"
                                                extraQueryParams={extraQueryParams}
                                                onProviderClick={beginSsoReauthentication}
                                            />
                                        ) : null}
                                    </div>
                                ) : null}

                                {showSetPasswordLink ? <QuillSetPasswordLinkPrompt /> : null}
                            </>
                        )}
                    </div>
                </DialogBody>
                {ssoEnforcement ? (
                    <DialogFooter>
                        <SSOEnforcedLoginButton
                            provider={ssoEnforcement}
                            email={user!.email}
                            size="medium"
                            extraQueryParams={extraQueryParams}
                            onProviderClick={beginSsoReauthentication}
                        />
                    </DialogFooter>
                ) : showPassword ? (
                    <DialogFooter>
                        <Button
                            variant="primary"
                            type="button"
                            form="reauthentication"
                            loading={isReauthenticationSubmitting}
                            onClick={submitReauthentication}
                        >
                            Re-authenticate
                        </Button>
                    </DialogFooter>
                ) : null}
            </DialogContent>
        </Dialog>
    )
}
