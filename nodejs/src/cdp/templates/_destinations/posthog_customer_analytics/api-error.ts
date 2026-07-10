export const hogApiErrorMessageFn = `fun apiErrorMessage(response) {
  return response.body.error ?? response.body.detail ?? response.body
}`
