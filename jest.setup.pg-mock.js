jest.mock('pg', () => {
    const mPool = {
        connect: jest.fn(),
        query: jest.fn(),
        end: jest.fn(),
    }
    return { Pool: jest.fn(() => mPool) }
})
