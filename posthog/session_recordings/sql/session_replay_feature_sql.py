def SESSION_REPLAY_FEATURES_DATA_TABLE():
    return "sharded_session_replay_features"


def TRUNCATE_SESSION_REPLAY_FEATURES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SESSION_REPLAY_FEATURES_DATA_TABLE()}"


# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)
