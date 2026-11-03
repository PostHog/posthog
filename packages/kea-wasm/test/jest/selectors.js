import { kea, resetContext, actions, reducers, selectors, key } from '../../src'

describe('selectors', () => {
  beforeEach(() => {
    resetContext({ createStore: true })
  })

  test('selectors have the store as a default', () => {
    const books = {
      1: 'book1',
      2: 'book2',
    }

    const logic = kea({
      reducers: ({ actions }) => ({
        books: [books, {}],
        bookId: [1, {}],
      }),

      selectors: ({ selectors }) => ({
        book: [() => [selectors.books, selectors.bookId], (books, bookId) => books[bookId]],
      }),
    })

    const unmount = logic.mount()

    expect(logic.selectors.books()).toEqual(books)
    expect(logic.selectors.bookId()).toEqual(1)
    expect(logic.selectors.book()).toEqual(books[1])

    unmount()
  })

  test('selectors have the store and props as a default', () => {
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

    const logicWithProps = logic({ extra: 'nope' })

    const unmount = logicWithProps.mount()

    expect(logicWithProps.selectors.books()).toEqual(books)
    expect(logicWithProps.selectors.bookId()).toEqual(1)
    expect(logicWithProps.selectors.book()).toEqual('book1nope')

    unmount()
  })

  test('inline props in selectors work after mounting', () => {
    // https://github.com/keajs/kea/issues/124
    // props passed to .build(props) were overridden by .mount(), which did behind the scenes .build({}).mount()
    const logic = kea({
      selectors: ({ props }) => ({
        valueFromSelectorsProps: [() => [], () => props.foo],
        valueFromInlineSelectorProps: [() => [(_, inlineProps) => inlineProps.foo], (foo) => foo],
      }),
    })

    logic.build({ foo: 'foo' })
    logic.mount()

    expect(logic.values.valueFromSelectorsProps).toEqual('foo')
    expect(logic.values.valueFromInlineSelectorProps).toEqual('foo')
  })

  test('selectors run only once when input has not changed', () => {
    const books = {
      1: 'book1',
      2: 'book2',
    }

    let selectorRan = 0

    const logic = kea({
      reducers: ({ actions }) => ({
        books: [books, {}],
        bookId: [1, {}],
      }),

      selectors: ({ selectors }) => ({
        book: [
          () => [selectors.books, selectors.bookId],
          (books, bookId) => {
            selectorRan += 1
            return books[bookId]
          },
        ],
      }),
    })

    const unmount = logic.mount()

    expect(logic.selectors.books()).toEqual(books)
    expect(logic.selectors.bookId()).toEqual(1)
    expect(logic.selectors.book()).toEqual(books[1])

    expect(selectorRan).toEqual(1)

    expect(logic.selectors.book()).toEqual(books[1])
    expect(logic.selectors.book()).toEqual(books[1])

    expect(selectorRan).toEqual(1)

    unmount()
  })

  test('support custom memoization functions', () => {
    const logic = kea([
      actions({
        addValue: (value) => ({ value }),
        setValue: (index, value) => ({ index, value }),
      }),
      reducers({
        values: [
          [],
          {
            addValue: (state, { value }) => [...state, value],
            setValue: (state, { index, value }) => state.map((s, i) => (i === index ? value : s)),
          },
        ],
      }),
      selectors({
        reversedValues: [(s) => [s.values], (values) => [...values].reverse()],
        reversedValuesIfLengthChanges: [
          (s) => [s.values],
          (values) => [...values].reverse(),
          { resultEqualityCheck: (a, b) => a.length === b.length },
        ],
      }),
    ])

    logic.mount()
    expect(logic.values.values).toEqual([])
    expect(logic.values.reversedValues).toEqual([])

    logic.actions.addValue('first')

    expect(logic.values.values).toEqual(['first'])
    expect(logic.values.reversedValues).toEqual(['first'])
    expect(logic.values.reversedValuesIfLengthChanges).toEqual(['first'])

    logic.actions.addValue('second')

    expect(logic.values.values).toEqual(['first', 'second'])
    expect(logic.values.reversedValues).toEqual(['second', 'first'])
    expect(logic.values.reversedValuesIfLengthChanges).toEqual(['second', 'first'])

    logic.actions.setValue(1, 'SECOND')

    expect(logic.values.values).toEqual(['first', 'SECOND'])
    expect(logic.values.reversedValues).toEqual(['SECOND', 'first'])
    // DID NOT CHANGE!
    expect(logic.values.reversedValuesIfLengthChanges).toEqual(['second', 'first'])

    logic.actions.addValue('third')

    expect(logic.values.values).toEqual(['first', 'SECOND', 'third'])
    expect(logic.values.reversedValues).toEqual(['third', 'SECOND', 'first'])
    expect(logic.values.reversedValuesIfLengthChanges).toEqual(['third', 'SECOND', 'first'])
  })

  test('props selectors', () => {
    const logic = kea([
      key((props) => props.id),
      selectors({
        id: [
          (s, p) => [p.id],
          (id) => {
            return id
          },
        ],
      }),
    ])

    const builtLogic = logic({ id: 1 })
    builtLogic.mount()

    expect(builtLogic.values.id).toEqual(1)
  })

  test('props selectors throw', () => {
    const logic = kea([
      key((props) => props.id),
      selectors({
        id: [
          (s, p) => [p.somethingElse],
          (id) => {
            return id
          },
        ],
      }),
    ])

    expect(() => {
      const builtLogic = logic({ id: 1 })
    }).toThrow(
      '[KEA] Prop "somethingElse" not found for logic "kea.logic.1.1". Attempted to use in a selector. Please specify a default via props({ somethingElse: \'\' }) to resolve.',
    )
  })
})
