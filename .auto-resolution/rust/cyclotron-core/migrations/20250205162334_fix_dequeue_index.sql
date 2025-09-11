-- Worker dequeue query uses priority, and then scheduled, as the ordering args. Original index was the wrong way around

CREATE INDEX idx_cyclotron_jobs_dequeue_correct_order ON cyclotron_jobs (queue_name, state, priority, scheduled)
WHERE
    state = 'available';
