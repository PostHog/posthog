import time
from random import randint

from clickhouse_driver import Client

from ee.clickhouse.experiments.columns_sql import (
    CREATE_COLS_TABLE,
    CREATE_JSON_TABLE,
    DROP_COLS_TABLE,
    DROP_JSON_TABLE,
    INSERT_COLS_TABLE,
    INSERT_JSON_TABLE,
    JSON_SELECT_LIMIT,
    SELECT_LIMIT,
)

SAMPLE_SIZE = 100
ROWS = 500
PROPERTIES_SIZE = 1000

# Tables:
# [x] JSON
# [x] Columns
# [ ] Materialized view


def execute(sql):
    client = Client(host="localhost", database="columns")
    return client.execute(sql)


# def create_database():
#     return execute(CREATE_COLS_DATABASE)
#
#
# def drop_database():
#     return execute(DROP_COLS_DATABASE)


def drop_cols_table():
    return execute(DROP_COLS_TABLE)


def create_cols_table():
    return execute(CREATE_COLS_TABLE)


def get_cols_properties():
    p_values = []
    for n in range(1, PROPERTIES_SIZE + 1):
        random_string = str(randint(1, 11))
        p_values.append("'value" + random_string + "'")
    properties = ",".join(p_values)
    return properties


def insert_cols_data():
    p_columns = []

    for n in range(1, PROPERTIES_SIZE + 1):
        p_columns.append("p" + str(n))

    cols = ",".join(p_columns)
    rows = []

    for n in range(1, ROWS + 1):
        rows.append("(generateUUIDv4(), '$pageview', " + get_cols_properties() + ")")

    insert = INSERT_COLS_TABLE.format(cols=cols, values=",".join(rows),)

    # return insert
    return execute(insert)


def time_cols_select_limit(num):
    sql = SELECT_LIMIT.format(limit=num)

    start = time.time()
    execute(sql)
    end = time.time()

    return end - start


def drop_json_table():
    execute(DROP_JSON_TABLE)


def create_json_table():
    execute(CREATE_JSON_TABLE)


def get_json_properties():
    p_values = []
    for n in range(1, PROPERTIES_SIZE + 1):
        random_string = str(randint(1, 11))
        p_values.append('"p' + str(n) + '": "value' + random_string + '"')
    properties = ",".join(p_values)
    return "'{" + properties + "}'"


def insert_json_data():
    rows = []

    for n in range(1, ROWS + 1):
        rows.append("(generateUUIDv4(), '$pageview', " + get_json_properties() + ")")

    insert = INSERT_JSON_TABLE.format(values=",".join(rows),)

    # return insert
    return execute(insert)


def time_json_select_limit(num):
    sql = JSON_SELECT_LIMIT.format(limit=num)

    start = time.time()
    execute(sql)
    end = time.time()

    return end - start


def sample(fn, sample_size, should_print=False):
    total = 0
    for n in range(1, sample_size + 1):
        time = fn()
        total += time
        if should_print:
            print(time)

    return total / sample_size


def run():
    drop_cols_table()
    create_cols_table()
    insert_cols_data()

    drop_json_table()
    create_json_table()
    insert_json_data()

    print("Columns:")
    cols_average = sample(lambda: time_cols_select_limit(500), SAMPLE_SIZE)
    print("average=" + str(cols_average))

    print("")
    print("JSON:")
    json_average = sample(lambda: time_json_select_limit(500), SAMPLE_SIZE)
    print("average=" + str(json_average))


run()

# Sample size: 1000
# Columns:
# average=0.01365275764465332
#
# JSON:
# average=0.026659546136856078

# Sample size: 100
# Columns:
# average=0.011378495693206788
#
# JSON:
# average=0.025627202987670898
