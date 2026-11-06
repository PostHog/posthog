if (process.env.CI) {
    jest.retryTimes(1, { logErrorsBeforeRetry: true })
}
