import { kea, resetContext } from '../../src'

describe('values', () => {
  beforeEach(() => {
    resetContext({ createStore: true })
  })

  test('logic.values reflects the current state', () => {
    const books = {
      1: 'book1',
      2: 'book2',
    }

    const logic = kea({
      reducers: () => ({
        books: [books, {}],
        bookId: [1, {}],
      }),

      selectors: ({ selectors }) => ({
        book: [
          () => [selectors.books, selectors.bookId, (_, props) => props.extra],
          (books, bookId, extra) => books[bookId] + extra,
        ],
      }),
    })

    const builtLogic = logic({ extra: 'nope' })
    const unmount = builtLogic.mount()

    expect(builtLogic.values.books).toEqual(books)
    expect(builtLogic.values.bookId).toEqual(1)
    expect(builtLogic.values.book).toEqual('book1nope')

    unmount()
  })

  test('cloning logic.values takes a snapshot of the current state', () => {
    const books = {
      1: 'book1',
      2: 'book2',
    }

    const logic = kea({
      actions: () => ({
        setBookId: (bookId) => ({ bookId }),
      }),

      reducers: ({ actions }) => ({
        books: [books, {}],
        bookId: [
          1,
          {
            [actions.setBookId]: (_, payload) => payload.bookId,
          },
        ],
      }),

      selectors: ({ selectors }) => ({
        book: [
          () => [selectors.books, selectors.bookId, (_, props) => props.extra],
          (books, bookId, extra) => books[bookId] + extra,
        ],
      }),
    })

    const builtLogic = logic({ extra: 'nope' })
    const unmount = builtLogic.mount()

    expect(builtLogic.values.books).toEqual(books)
    expect(builtLogic.values.bookId).toEqual(1)
    expect(builtLogic.values.book).toEqual('book1nope')

    const clonedValues = { ...builtLogic.values }

    builtLogic.actions.setBookId(2)

    expect(builtLogic.values.books).toEqual(books)
    expect(builtLogic.values.bookId).toEqual(2)
    expect(builtLogic.values.book).toEqual('book2nope')

    expect(clonedValues.books).toEqual(books)
    expect(clonedValues.bookId).toEqual(1)
    expect(clonedValues.book).toEqual('book1nope')

    unmount()
  })
})
