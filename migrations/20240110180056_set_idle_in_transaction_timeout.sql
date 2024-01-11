-- If running worker in transactional mode, this ensures we clean up any open transactions.
ALTER USER current_user SET idle_in_transaction_session_timeout = '2min';
