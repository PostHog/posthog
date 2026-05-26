# Forms

Use `kea-forms` for any form. It manages values, validation, submission state, and
success/failure actions in one builder. Hand-rolling a form means rebuilding all of
that for no good reason.

## Why a forms builder and not reducers + listeners

A `forms` builder named `foo` generates:

- `fooValues` — current values
- `fooValidationErrors` — keyed by field, computed from `errors`
- `fooHasErrors` — boolean
- `setFooValues({ a: 1 })` / `setFooValue('a', 1)` — partial updates
- `submitFoo()` / `submitFooSuccess` / `submitFooFailure`
- `isFooSubmitting` — boolean
- `resetFoo(defaults?)` — back to defaults
- `<Form logic={fooLogic} formKey="foo">` and `<Field name="...">` on the component side

You can't beat that with hand-written reducers without rewriting all of it.

## Basic shape

```ts
import { forms } from 'kea-forms'

export interface SignupForm {
    email: string
    organization_name: string
}

forms(() => ({
    signup: {
        defaults: { email: '', organization_name: '' } as SignupForm,
        errors: ({ email, organization_name }) => ({
            email: !email ? 'Please enter your email' : undefined,
            organization_name: !organization_name ? 'Please enter your org' : undefined,
        }),
        submit: async (formValues) => {
            await api.create('api/social_signup/', formValues)
        },
    },
})),
```

- `defaults` — initial values (typed).
- `errors` — function from values to a per-field error object. Return `undefined`
  for "no error" — never an empty string.
- `submit` — async function; throws are caught by the plugin and surface as
  `submitFooFailure`.

## Field-dependent and conditional errors

```ts
errors: ({ source_type, s3_bucket, access_key }) => ({
    source_type: !source_type ? 'Pick a source' : undefined,
    s3_bucket: source_type === 's3' && !s3_bucket ? 'Bucket required' : undefined,
    access_key: source_type === 's3' && !access_key ? 'Access key required' : undefined,
}),
```

The errors function re-runs on every value change, so it naturally supports cross-field
validation. Keep it pure — no I/O, no `Math.random()`.

## Reacting to submit success or failure

```ts
listeners(({ actions }) => ({
    submitSignupSuccess: () => {
        router.actions.push(urls.home())
    },
    submitSignupFailure: ({ error }) => {
        lemonToast.error(error.message ?? 'Something went wrong')
    },
})),
```

Don't put navigation or toasts inside `submit` — let the success/failure listeners
handle them. Submit is for the actual work; reacting to outcomes is a listener concern.

## Resetting

```ts
listeners(({ actions }) => ({
    submitSignupSuccess: () => {
        actions.resetSignup()              // back to defaults
        // or: actions.resetSignup({ email: values.signup.email })  // partial reset
    },
})),
```

## On the component side

```tsx
import { Form, Field } from 'kea-forms'
;<Form logic={signupLogic} formKey="signup" enableFormOnSubmit>
  <Field name="email" label="Email">
    <LemonInput type="email" />
  </Field>
  <Field name="organization_name" label="Org">
    <LemonInput />
  </Field>
  <LemonButton type="primary" htmlType="submit" loading={isSignupSubmitting}>
    Sign up
  </LemonButton>
</Form>
```

`enableFormOnSubmit` makes Enter submit the form. Use it unless you have a reason
not to.

## Anti-patterns

See [anti-patterns.md](anti-patterns.md) for the consolidated catalogue.
