jest.mock('ioredis', () => {
    const mPool = {
        get: jest.fn(),
        set: jest.fn(),
        disconnect: jest.fn(),
    }
    return jest.fn(() => mPool)
})
